"""Compact assistant artifacts for model input without changing stored messages."""

from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

from langchain_core.messages import AIMessage, BaseMessage


_HTML_FENCE = re.compile(
    r"^[ \t]*(?P<fence>(?P<mark>`|~)(?P=mark){2,})[ \t]*html?[ \t]*\r?\n"
    r"(?P<body>.*?)(?:\r?\n[ \t]*(?P=fence)(?P=mark)*[ \t]*(?=\r?$)|\Z)",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)
_DOCUMENT = re.compile(
    r"(?:<!doctype\s+html\b[^>]*>\s*)?<html\b[^>]*>.*?</html\s*>",
    re.IGNORECASE | re.DOTALL,
)
_ARTIFACT_TAG = re.compile(r"<!doctype\s+html\b|<html\b|<iframe\b", re.IGNORECASE)
_DATA_IMAGE = re.compile(r"data:image/[^\s,;\"'<>]+;base64,[A-Za-z0-9+/=]+", re.IGNORECASE)


class _ArtifactSummary(HTMLParser):
    """Keep a bounded amount of visible context plus ordinary links and image IDs."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.text = ""
        self.links = []
        self.image_ids = []
        self.hidden = 0
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag == "title":
            self.in_title = True
        attrs = dict(attrs)
        if tag == "img" and attrs.get("alt") and len(self.image_ids) < 3:
            self.image_ids.append(attrs["alt"][:160])
        url = attrs.get("href") if tag == "a" else attrs.get("src") if tag == "iframe" else None
        if url and len(url) <= 512 and url not in self.links and len(self.links) < 3:
            try:
                parsed = urlsplit(url)
            except ValueError:
                return
            if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password:
                self.links.append(url)

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.hidden:
            return
        if self.in_title:
            self.title = (self.title + data)[:120]
        elif data.strip() and len(self.text) < 500:
            self.text = (self.text + " " + " ".join(data.split()))[:500]


def _summarize_html(html: str) -> str:
    parser = _ArtifactSummary()
    parser.feed(html)
    parts = ["HTML artifact đã lược khỏi context LLM"]
    if parser.title.strip():
        parts.append("tiêu đề: " + parser.title.strip())
    if parser.text.strip():
        parts.append("nội dung: " + parser.text.strip())
    if parser.image_ids:
        parts.append("ID/ảnh: " + ", ".join(parser.image_ids))
    if parser.links:
        parts.append("URL: " + ", ".join(parser.links))
    return "[" + "; ".join(parts) + "]"


def _compact_text(text: str) -> str:
    def replace_fence(match):
        body = match["body"]
        return _summarize_html(body) if _ARTIFACT_TAG.search(body) else match[0]

    text = _HTML_FENCE.sub(replace_fence, text)
    text = _DOCUMENT.sub(lambda match: _summarize_html(match[0]), text)
    return _DATA_IMAGE.sub("[Ảnh base64 đã lược khỏi context LLM]", text)


def messages_for_llm(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Sanitize only assistant text; retain user inputs, tool results, and IDs verbatim."""
    result = []
    for message in messages:
        if not isinstance(message, AIMessage):
            result.append(message)
            continue
        content = message.content
        if isinstance(content, str):
            compact = _compact_text(content)
        else:
            compact = []
            for block in content:
                if isinstance(block, str):
                    compact.append(_compact_text(block))
                elif isinstance(block, dict) and isinstance(block.get("text"), str):
                    compact.append({**block, "text": _compact_text(block["text"])})
                else:
                    compact.append(block)
        result.append(message.model_copy(update={"content": compact}) if compact != content else message)
    return result
