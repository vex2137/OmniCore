"""Opt-in, read-only web tools: public HTTP(S) only, pinned DNS, bounded responses."""

import codecs
import ipaddress
import re
import socket
import time
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit

import httpx
from pydantic import Field

from omnicore.schemas import WireModel
from omnicore.text.types import TextError

MAX_BYTES = 2_000_000
CHUNK = 3500
SEARCH_URL = "https://html.duckduckgo.com/html/"
TEXT_TYPES = ("text/html", "text/plain", "application/xhtml+xml", "application/json", "text/xml")
USER_AGENT = "OmniCore-agent/0.2 (+https://github.com/vex2137/OmniCore; user-initiated)"


class FetchArgs(WireModel):
    url: str = Field(min_length=8, max_length=2048)
    start: int = Field(default=0, ge=0, le=MAX_BYTES)


class SearchArgs(WireModel):
    query: str = Field(min_length=1, max_length=256)


def public_address(host, port):
    """Resolve once and refuse loopback, private, link-local and reserved targets."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        raise TextError("agent_web_unreachable", 502) from None
    addresses = []
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if address.version == 6 and address.ipv4_mapped:
            address = address.ipv4_mapped
        if not address.is_global or address.is_multicast:
            raise TextError("agent_web_blocked", 403)
        addresses.append(address)
    if not addresses:
        raise TextError("agent_web_unreachable", 502)
    return addresses[0]


def validate_url(url):
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise TextError("agent_web_blocked", 403)
    if parts.username or parts.password:
        raise TextError("agent_web_blocked", 403)
    if parts.port not in {None, 80, 443, 8080, 8443}:
        raise TextError("agent_web_blocked", 403)
    return parts


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template", "iframe", "head"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "pre"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.title, self.depth, self.in_title = [], "", 0, False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.in_title = True
        elif tag in self.SKIP:
            self.depth += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        elif tag in self.SKIP and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif not self.depth:
            self.parts.append(data)


def html_text(body):
    parser = _Text()
    parser.feed(body)
    text = re.sub(r"[ \t\r\f\v]+", " ", "".join(parser.parts))
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return " ".join(parser.title.split())[:300], text


def _clean(value):
    return " ".join(unescape(re.sub(r"<[^>]+>", "", value)).split())


class WebTools:
    def __init__(self, transport=None, resolver=public_address):
        self.transport, self.resolver = transport, resolver

    def _get(self, url, cancelled, params=None):
        """GET with each redirect hop re-validated and connected to the checked address."""
        started = time.monotonic()
        for _ in range(4):
            parts = validate_url(url)
            port = parts.port or (443 if parts.scheme == "https" else 80)
            address = self.resolver(parts.hostname, port)
            host = f"[{address}]" if address.version == 6 else str(address)
            netloc = host if parts.port is None else f"{host}:{parts.port}"
            target = parts._replace(netloc=netloc).geturl()
            # trust_env=False: no proxy could re-resolve the host behind the pinned address.
            with httpx.Client(
                timeout=10, follow_redirects=False, trust_env=False, transport=self.transport
            ) as client:
                request = client.build_request(
                    "GET",
                    target,
                    params=params,
                    headers={"Host": parts.netloc.rsplit("@", 1)[-1], "User-Agent": USER_AGENT},
                    extensions={"sni_hostname": parts.hostname},
                )
                response = client.send(request, stream=True)
                try:
                    if response.is_redirect:
                        location = response.headers.get("location", "")
                        url, params = urljoin(url, location), None
                        continue
                    if response.status_code in {403, 429}:
                        raise TextError("agent_web_refused", 502)
                    if response.status_code >= 400:
                        raise TextError("agent_web_http_error", 502)
                    kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
                    if kind and kind not in TEXT_TYPES:
                        raise TextError("agent_web_unsupported_content", 415)
                    body = bytearray()
                    for block in response.iter_bytes():
                        if cancelled.is_set():
                            raise TextError("agent_cancelled", 409)
                        body.extend(block)
                        if len(body) > MAX_BYTES or time.monotonic() - started > 15:
                            raise TextError("agent_result_limit", 422)
                    encoding = response.charset_encoding or "utf-8"
                    try:
                        codecs.lookup(encoding)
                    except LookupError:
                        encoding = "utf-8"
                    return url, kind, bytes(body).decode(encoding, errors="replace")
                finally:
                    response.close()
        raise TextError("agent_web_redirect_limit", 502)

    def fetch(self, args, cancelled):
        try:
            url, kind, body = self._get(args.url, cancelled)
        except httpx.HTTPError:
            raise TextError("agent_web_unreachable", 502) from None
        title, text = html_text(body) if "html" in kind or not kind else ("", body.strip())
        chunk = text[args.start : args.start + CHUNK]
        following = args.start + CHUNK
        return {
            "url": url,
            "title": title,
            "text": chunk,
            "start": args.start,
            "next_start": following if following < len(text) else None,
            "total_chars": len(text),
        }

    def search(self, args, cancelled):
        try:
            _, _, body = self._get(SEARCH_URL + "?q=" + quote(args.query), cancelled)
        except httpx.HTTPError:
            raise TextError("agent_web_unreachable", 502) from None
        results = []
        pattern = re.compile(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>'
            r'(?:.*?class="result__snippet"[^>]*>(.*?)</a>)?',
            re.S,
        )
        for href, title, snippet in pattern.findall(body):
            href = unescape(href)
            if "duckduckgo.com/l/" in href:
                href = unquote(parse_qs(urlsplit(href).query).get("uddg", [""])[0])
            if urlsplit(href).scheme not in {"http", "https"}:
                continue
            results.append(
                {"url": href, "title": _clean(title)[:200], "snippet": _clean(snippet)[:300]}
            )
            if len(results) >= 8:
                break
        if not results and "result__a" not in body:
            # Includes anti-bot interstitials: report, never attempt to bypass them.
            raise TextError("agent_web_search_unavailable", 502)
        return {"query": args.query, "results": results}
