"""Content search and opt-in web tools with a mocked transport; no live network access."""

import asyncio
import ipaddress
import json
import threading

import httpx
import pytest
from test_agents import FINAL, finish, setup, tool

from omnicore.agents.service import AgentSettings
from omnicore.agents.tools import FileTools, FindArgs, schemas
from omnicore.agents.web import FetchArgs, SearchArgs, WebTools, public_address
from omnicore.text.types import TextError

PUBLIC = ipaddress.ip_address("93.184.216.34")


def web(handler):
    return WebTools(transport=httpx.MockTransport(handler), resolver=lambda host, port: PUBLIC)


def test_search_text_matches_lines_and_skips_sensitive_and_binary(tmp_path):
    folder = tmp_path / "data"
    (folder / "sub").mkdir(parents=True)
    (folder / "a.txt").write_text("alpha\nNeedle here\nomega\n")
    (folder / "sub" / "b.md").write_text("no\nanother NEEDLE\n")
    (folder / "secret.txt").write_text("needle in secret\n")
    (folder / "blob.bin").write_bytes(b"\xff\xfeneedle")
    files = FileTools()
    grant = files.grant("c", folder)
    result = files.read(
        "search_text", FindArgs(grant_id=grant["id"], query="needle"), "c", threading.Event()
    )
    found = sorted((entry["path"], entry["line"]) for entry in result["entries"])
    assert found == [("a.txt", 2), ("sub/b.md", 2)]
    files.close()


def test_web_tools_are_hidden_without_consent():
    names = lambda settings: {s["function"]["name"] for s in schemas(settings)}  # noqa: E731
    assert not {"web_search", "web_fetch"} & names(AgentSettings())
    assert {"web_search", "web_fetch", "search_text"} <= names(AgentSettings(web_access=True))


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "ftp://example.com/x", "http://user:pw@example.com/", "http://x:22/"],
)
def test_web_rejects_unsafe_urls(url):
    with pytest.raises(TextError) as error:
        web(lambda r: httpx.Response(200)).fetch(FetchArgs(url=url), threading.Event())
    assert error.value.code == "agent_web_blocked"


@pytest.mark.parametrize("host", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1"])
def test_resolver_blocks_private_targets(host):
    with pytest.raises(TextError) as error:
        public_address(host, 80)
    assert error.value.code == "agent_web_blocked"


def test_fetch_extracts_text_pins_address_and_pages():
    seen = []
    body = "<html><head><title>T</title><script>x()</script></head><body><p>Hello</p>"
    body += "<p>" + "word " * 2000 + "</p></body></html>"

    def handler(request):
        seen.append(request)
        return httpx.Response(200, html=body)

    result = web(handler).fetch(FetchArgs(url="https://example.com/page"), threading.Event())
    assert result["title"] == "T" and result["text"].startswith("Hello")
    assert "x()" not in result["text"] and result["next_start"] == 3500
    assert seen[0].url.host == str(PUBLIC) and seen[0].headers["host"] == "example.com"
    assert seen[0].extensions["sni_hostname"] == "example.com"
    second = web(handler).fetch(
        FetchArgs(url="https://example.com/page", start=result["next_start"]), threading.Event()
    )
    assert second["start"] == 3500 and second["text"]


def test_redirect_to_private_address_is_blocked():
    tools = WebTools(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(302, headers={"location": "http://internal.local/"})
        ),
        resolver=lambda host, port: (
            PUBLIC if host == "example.com" else public_address("127.0.0.1", port)
        ),
    )
    with pytest.raises(TextError) as error:
        tools.fetch(FetchArgs(url="https://example.com/"), threading.Event())
    assert error.value.code == "agent_web_blocked"


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (
            httpx.Response(200, content=b"\x00", headers={"content-type": "image/png"}),
            "agent_web_unsupported_content",
        ),  # noqa: E501
        (httpx.Response(429), "agent_web_refused"),
        (httpx.Response(500), "agent_web_http_error"),
    ],
)
def test_fetch_errors_are_explicit(response, code):
    with pytest.raises(TextError) as error:
        web(lambda r: response).fetch(FetchArgs(url="https://example.com/"), threading.Event())
    assert error.value.code == code


def test_search_parses_results_and_reports_interstitials():
    html = (
        '<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg='
        'https%3A%2F%2Fdocs.python.org%2F3%2F&amp;rut=x">Python <b>docs</b></a>'
        '<a class="result__snippet" href="#">Official documentation</a>'
    )
    result = web(lambda r: httpx.Response(200, html=html)).search(
        SearchArgs(query="python"), threading.Event()
    )
    assert result["results"] == [
        {
            "url": "https://docs.python.org/3/",
            "title": "Python docs",
            "snippet": "Official documentation",
        }
    ]
    with pytest.raises(TextError) as error:
        web(lambda r: httpx.Response(200, html="<p>Please verify</p>")).search(
            SearchArgs(query="x"), threading.Event()
        )
    assert error.value.code == "agent_web_search_unavailable"


def test_agent_refuses_web_without_consent_and_uses_it_with_consent(tmp_path):
    async def exercise():
        agents, conv, engine = setup(tmp_path, [])
        agents.web = web(lambda r: httpx.Response(200, html="<p>Public page</p>"))
        engine.responses = iter([tool("web_fetch", url="https://example.com/"), FINAL])
        denied = await finish(agents, conv)
        assert denied["steps"][0]["error_code"] == "agent_web_disabled"
        assert "Internet access: disabled" in engine.messages[0][0].content
        agents.store.save_job(
            "agent-settings",
            conv.id,
            AgentSettings(mode="agent", web_access=True).model_dump(),
        )
        engine.responses = iter([tool("web_fetch", url="https://example.com/"), FINAL])
        allowed = await finish(agents, conv)
        assert allowed["state"] == "completed"
        assert allowed["steps"][0]["state"] == "completed"
        assert allowed["steps"][0]["summary"] == "https://example.com/"
        assert "Public page" in engine.messages[-1][-1].content
        assert "Public page" not in json.dumps(agents.store.jobs("agent-run"))
        await agents.close()
        await agents.service.generations.close()

    asyncio.run(exercise())
