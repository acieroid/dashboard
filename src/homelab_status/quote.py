from __future__ import annotations

import json
import logging
import os
import threading
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("homelab_status.quote")


@dataclass(frozen=True, slots=True)
class DailyQuote:
    text: str
    author: str | None = None

    def display(self) -> str:
        return f"“{self.text}” — {self.author}" if self.author else f"“{self.text}”"


class DailyQuoteCache:
    def __init__(
        self,
        cache_path: Path,
        url: str,
        fallback: str,
        timeout_seconds: float = 5.0,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self.cache_path = cache_path
        self.url = url
        self.fallback = DailyQuote(fallback)
        self.timeout_seconds = timeout_seconds
        self.opener = opener
        self._lock = threading.Lock()

    def get(self, day: date) -> DailyQuote:
        cached = self._read_cache()
        if cached and cached[0] == day.isoformat():
            return cached[1]
        with self._lock:
            cached = self._read_cache()
            if cached and cached[0] == day.isoformat():
                return cached[1]
            try:
                quote = self._fetch()
                self._write_cache(day, quote)
                return quote
            except (OSError, ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError):
                logger.warning("daily_quote_fetch_failed", exc_info=True)
                return cached[1] if cached else self.fallback

    def _fetch(self) -> DailyQuote:
        request = urllib.request.Request(
            self.url,
            headers={"Accept": "application/json", "User-Agent": "homelab-status/0.1"},
        )
        with self.opener(request, timeout=self.timeout_seconds) as response:
            payload = json.load(response)
        if isinstance(payload, list):
            item = payload[0]
            text_value = item["q"]
            author_value = item.get("a", "")
        else:
            # Retain compatibility with an explicitly configured They Said So URL.
            item = payload["contents"]["quotes"][0]
            text_value = item["quote"]
            author_value = item.get("author", "")
        text = " ".join(str(text_value).split())
        author = " ".join(str(author_value).split()) or None
        if not 8 <= len(text) <= 300:
            raise ValueError("daily quote length is outside accepted bounds")
        return DailyQuote(text, author)

    def _read_cache(self) -> tuple[str, DailyQuote] | None:
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            text = str(payload["text"])
            author = str(payload["author"]) if payload.get("author") else None
            return str(payload["date"]), DailyQuote(text, author)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return None

    def _write_cache(self, day: date, quote: DailyQuote) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_suffix(".tmp")
        payload = {"date": day.isoformat(), "text": quote.text, "author": quote.author}
        try:
            temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, self.cache_path)
        finally:
            if temporary.exists():
                temporary.unlink()
