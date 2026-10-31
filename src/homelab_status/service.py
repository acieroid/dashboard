from __future__ import annotations

from datetime import UTC, datetime

from .config import Settings
from .database import Database
from .freshness import classify


def status_snapshot(settings: Settings, database: Database, now: datetime | None = None) -> dict[str, object]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    reports = database.latest_reports()
    peers: list[dict[str, object]] = []
    for configured_peer in settings.peers:
        stored = reports.get(configured_peer.name)
        received = datetime.fromisoformat(str(stored["received_at"])) if stored else None
        age = max(0, int((current - received.astimezone(UTC)).total_seconds())) if received else None
        peers.append(
            {
                "name": configured_peer.name,
                "state": classify(
                    received,
                    current,
                    settings.stale_after_seconds,
                    settings.missing_after_seconds,
                ),
                "age_seconds": age,
                "received_at": received.isoformat() if received else None,
                "report": stored["report"] if stored else None,
            }
        )
    return {"generated_at": current.isoformat(), "peers": peers}

