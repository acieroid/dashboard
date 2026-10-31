from __future__ import annotations

import json
from datetime import date
from io import BytesIO
from pathlib import Path

from homelab_status.quote import DailyQuoteCache


class Response(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def test_fetches_and_persists_daily_quote(tmp_path: Path) -> None:
    calls = []
    payload = {
        "contents": {
            "quotes": [
                {"quote": "  Make each day useful.  ", "author": "Someone"}
            ]
        }
    }

    def opener(request, timeout):
        calls.append(request.full_url)
        return Response(json.dumps(payload).encode())

    cache_path = tmp_path / "quote.json"
    cache = DailyQuoteCache(cache_path, "https://quotes.test/qod", "Fallback", opener=opener)
    first = cache.get(date(2026, 10, 30))
    second = DailyQuoteCache(cache_path, "https://quotes.test/qod", "Fallback", opener=opener).get(
        date(2026, 10, 30)
    )

    assert first.display() == "“Make each day useful.” — Someone"
    assert second == first
    assert calls == ["https://quotes.test/qod"]


def test_parses_zenquotes_today_response(tmp_path: Path) -> None:
    payload = [{"q": "  Make each day useful.  ", "a": "Someone", "h": "unused"}]

    def opener(request, timeout):
        return Response(json.dumps(payload).encode())

    cache = DailyQuoteCache(tmp_path / "quote.json", "https://zenquotes.io/api/today", "Fallback", opener=opener)
    assert cache.get(date(2026, 10, 30)).display() == "“Make each day useful.” — Someone"


def test_uses_configured_fallback_when_first_fetch_fails(tmp_path: Path) -> None:
    def opener(request, timeout):
        raise OSError("offline")

    cache = DailyQuoteCache(tmp_path / "quote.json", "https://quotes.test/qod", "Keep going.", opener=opener)
    assert cache.get(date(2026, 10, 30)).display() == "“Keep going.”"
