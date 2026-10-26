from __future__ import annotations

import logging
import re
import asyncio
from html.parser import HTMLParser
import httpx

logger = logging.getLogger(__name__)
PAGE_FETCH_TIMEOUT_SECONDS = 6.0

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class _HTMLStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.text_parts: list[str] = []
        self._skip: list[str] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if self._skip:
            if tag not in {"br", "img", "meta", "link", "input", "hr", "source", "wbr"}:
                self._skip.append(tag)
            return
        if tag in {"script", "style", "nav", "header", "footer", "aside", "noscript", "svg", "form"} or values.get("aria-hidden") == "true" or "hidden" in values:
            self._skip.append(tag)
        elif tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "br", "section", "article"}:
            self.text_parts.append("\n")
        elif tag in {"td", "th"}:
            self.text_parts.append(" | ")

    def handle_endtag(self, tag):
        if self._skip:
            if tag in self._skip:
                del self._skip[len(self._skip) - 1 - self._skip[::-1].index(tag):]
        elif tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "section", "article"}:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.text_parts.append(data + " ")


class _SectionParser(HTMLParser):
    """Extract heading-delimited sections from static HTML."""

    def __init__(self) -> None:
        super().__init__()
        self._heading_tag: str | None = None
        self._heading_text: list[str] = []
        self._heading_id = ""
        self._section_parts: list[str] = []
        self.sections: list[tuple[str, str, str]] = []
        self._active = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            if self._active:
                self.sections.append((self._heading_id, " ".join(self._heading_text), " ".join(self._section_parts)))
            self._heading_tag = tag.lower()
            self._heading_text = []
            self._section_parts = []
            self._heading_id = dict(attrs).get("id") or dict(attrs).get("name") or ""
            self._active = True

    def handle_endtag(self, tag: str) -> None:
        if self._heading_tag == tag.lower():
            self._heading_tag = None

    def handle_data(self, data: str) -> None:
        text = re.sub(r"\s+", " ", data).strip()
        if not text:
            return
        if self._heading_tag:
            self._heading_text.append(text)
        elif self._active:
            self._section_parts.append(text)

    def close(self) -> None:
        super().close()
        if self._active:
            self.sections.append((self._heading_id, " ".join(self._heading_text), " ".join(self._section_parts)))


async def fetch_page(url: str) -> str | None:
    try:
        headers = {"User-Agent": USER_AGENT}
        timeout = httpx.Timeout(connect=5.0, read=2.0, write=5.0, pool=5.0)
        async with asyncio.timeout(PAGE_FETCH_TIMEOUT_SECONDS):
            async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
                async with client.stream("GET", url) as resp:
                    if resp.status_code != 200:
                        return None
                    content_type = resp.headers.get("content-type", "text/html").lower()
                    if not any(kind in content_type for kind in ("text/html", "application/xhtml", "text/plain")):
                        return None
                    content = bytearray()
                    async for chunk in resp.aiter_bytes():
                        if len(content) + len(chunk) > 2_000_000:
                            logger.warning("page_reader_response_too_large")
                            return None
                        content.extend(chunk)
                    return content.decode(resp.encoding or "utf-8", errors="replace")
    except Exception:
        logger.error("Failed to fetch page %s", url, exc_info=True)
        return None


def extract_relevant_text(html: str, query: str, max_chars: int = 1200) -> str:
    cleaned = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)

    stripper = _HTMLStripper()
    stripper.feed(cleaned)
    stripper.close()
    raw_text = "".join(stripper.text_parts)

    stop_words = {
        "and", "the", "for", "with", "which", "one", "should", "buy", "tell",
        "about", "what", "are", "from", "this", "that", "into", "your", "you",
        "compare", "popular", "best", "under", "price", "prices", "current", "using", "sources",
    }
    query_words = [
        w.lower() for w in re.findall(r"\b\w{3,}\b", query)
        if w.lower() not in stop_words
    ]
    if not query_words or not raw_text:
        return ""

    sentences = list(dict.fromkeys(
        re.sub(r"\s+", " ", s).strip()
        for s in re.split(r"\n+|(?<=[.!?।])\s+", raw_text) if s.strip()
    ))
    scored_sentences = [
        ((sum(1 for word in set(query_words) if word in s.lower()) +
          min(3, len(re.findall(r"(?:\d[\d,.]*\s*[A-Za-z%][A-Za-z0-9/%-]*|[₹$€£]\s*\d[\d,.]*|\b(?:Rs\.?|INR|USD|EUR|GBP)\s*\d[\d,.]*)", s, re.I)))) / (1 + len(s) / 400), s)
        for s in sentences
        if any(word in s.lower() for word in query_words)
        if not re.search(r"cookie|sign in|newsletter|skip to content|add to cart|all rights reserved", s, re.I)
    ]
    matched_sentences = [
        sentence for score, sentence in sorted(
            ((score, sentence) for score, sentence in scored_sentences if score > 0),
            key=lambda item: item[0],
            reverse=True,
        )
    ]

    joined = " ".join(matched_sentences)
    return joined[:max_chars]


def extract_section(html: str, section: str, max_chars: int = 1600) -> tuple[str, str]:
    """Return matching heading content and its anchor, if the page has one."""
    parser = _SectionParser()
    parser.feed(re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE))
    parser.close()
    wanted = {word.lower() for word in re.findall(r"\b\w{3,}\b", section)}
    if not wanted:
        return "", ""
    for anchor, heading, body in parser.sections:
        heading_words = {word.lower() for word in re.findall(r"\b\w{3,}\b", heading)}
        if wanted.issubset(heading_words) or wanted & heading_words:
            text = re.sub(r"\s+", " ", f"{heading}. {body}").strip()
            return text[:max_chars], anchor
    return "", ""
