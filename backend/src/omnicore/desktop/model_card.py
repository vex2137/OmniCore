"""Convert untrusted model-card HTML to text before safe Markdown rendering."""

import re
from html.parser import HTMLParser


class CardHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.suppressed = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "iframe", "object", "svg"}:
            self.suppressed += 1
        elif not self.suppressed:
            if tag in {"p", "div", "br", "tr", "details", "summary", "h1", "h2", "h3", "li"}:
                self.parts.append("\n")
            if tag in {"h1", "h2", "h3"}:
                self.parts.append("#" * int(tag[1]) + " ")
            elif tag in {"td", "th"}:
                self.parts.append(" | ")
            elif tag == "li":
                self.parts.append("- ")
            elif tag in {"b", "strong"}:
                self.parts.append("**")
            elif tag in {"em", "i"}:
                self.parts.append("*")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "iframe", "object", "svg"}:
            self.suppressed = max(0, self.suppressed - 1)
        elif not self.suppressed:
            if tag in {"b", "strong"}:
                self.parts.append("**")
            elif tag in {"em", "i"}:
                self.parts.append("*")
            elif tag in {"p", "div", "tr", "details", "summary", "h1", "h2", "h3", "li"}:
                self.parts.append("\n")

    def handle_data(self, data):
        if not self.suppressed:
            self.parts.append(data)


def safe_card_markdown(text):
    # Preserve fenced code samples, where angle brackets are intended as text.
    text = re.sub(r"\A---\s*\n.*?\n---\s*(?:\n|\Z)", "", text, count=1, flags=re.DOTALL)
    chunks = re.split(r"(?ms)(^```[^\n]*\n.*?^```[^\n]*$)", text)
    for index in range(0, len(chunks), 2):
        parser = CardHTML()
        parser.feed(chunks[index])
        parser.close()
        cleaned = "".join(parser.parts)
        cleaned = re.sub(r"!\[([^]]*)\]\([^)]*\)", r"\1", cleaned)
        chunks[index] = re.sub(r"!\[([^]]*)\]\[[^]]*\]", r"\1", cleaned)
    return "".join(chunks)
