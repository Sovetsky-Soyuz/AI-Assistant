from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen


class NewsError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class NewsService:
    default_topic: str = "top headlines"

    def fetch_news(self, topic: str | None = None, max_items: int = 5) -> dict[str, Any]:
        cleaned_topic = (topic or self.default_topic).strip() or self.default_topic
        clamped_items = max(1, min(int(max_items or 5), 8))
        feed_url = self._build_feed_url(cleaned_topic)
        xml_text = self._request_text(feed_url)

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            raise NewsError(f"Could not read the latest news feed right now: {exc}") from exc

        items: list[dict[str, str]] = []
        for item in root.findall(".//item")[:clamped_items]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            source = (item.findtext("source") or "").strip()
            published_at = (item.findtext("pubDate") or "").strip()
            if not title or not link:
                continue
            items.append(
                {
                    "title": title,
                    "link": link,
                    "source": source or "Google News",
                    "published_at": published_at,
                }
            )

        if not items:
            raise NewsError("I could not find any fresh headlines for that topic right now.")

        return {
            "topic": cleaned_topic,
            "items": items,
            "updated_at": utc_now(),
        }

    def _build_feed_url(self, topic: str) -> str:
        normalized = topic.strip().lower()
        if normalized in {"top headlines", "headlines", "top news", "latest news", "news"}:
            return "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"
        query = quote_plus(topic)
        return f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

    def _request_text(self, url: str) -> str:
        request = Request(
            url,
            headers={
                "User-Agent": "Orbit-Assistant/1.0",
                "Accept": "application/rss+xml, application/xml, text/xml",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                return response.read().decode("utf-8")
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            detail = getattr(exc, "reason", None) or getattr(exc, "msg", None) or str(exc) or exc.__class__.__name__
            raise NewsError(f"News service unavailable right now: {detail}") from exc
