from __future__ import annotations

import logging
import re
from html.parser import HTMLParser
import httpx

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class _HTMLStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.text_parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.text_parts.append(data)


async def fetch_page(url: str) -> str | None:
    try:
        headers = {"User-Agent": USER_AGENT}
        async with httpx.AsyncClient(timeout=5.0, headers=headers) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.text
            return None
    except Exception:
        logger.error("Failed to fetch page %s", url, exc_info=True)
        return None


def extract_relevant_text(html: str, query: str, max_chars: int = 1200) -> str:
    cleaned = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)

    stripper = _HTMLStripper()
    stripper.feed(cleaned)
    raw_text = re.sub(r"\s+", " ", "".join(stripper.text_parts)).strip()

    query_words = [w.lower() for w in re.findall(r"\b\w{3,}\b", query)]
    if not query_words or not raw_text:
        return ""

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", raw_text) if s.strip()]
    matched_sentences = [
        s for s in sentences
        if any(w in s.lower() for w in query_words)
    ]

    joined = " ".join(matched_sentences)
    return joined[:max_chars]
