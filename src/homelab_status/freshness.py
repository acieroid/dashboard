from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal


Freshness = Literal["fresh", "stale", "missing"]


def classify(received_at: datetime | None, now: datetime, stale_after: int, missing_after: int) -> Freshness:
    if received_at is None:
        return "missing"
    age = max(0.0, (now.astimezone(UTC) - received_at.astimezone(UTC)).total_seconds())
    if age <= stale_after:
        return "fresh"
    if age <= missing_after:
        return "stale"
    return "missing"

