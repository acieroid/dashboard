from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterator

from .models import StatusReport


SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY,
    peer_ip TEXT NOT NULL,
    peer_name TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    collected_at TEXT NOT NULL,
    received_at TEXT NOT NULL,
    report_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS reports_peer_received_idx
ON reports(peer_name, received_at DESC, id DESC);
"""


class Database:
    def __init__(self, path: Path, retention_days: int = 30) -> None:
        self.path = path
        self.retention_days = retention_days

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            connection.commit()

    def insert_report(
        self,
        peer_name: str,
        peer_ip: str,
        report: StatusReport,
        received_at: datetime,
    ) -> int:
        cutoff = received_at - timedelta(days=self.retention_days)
        payload = report.model_dump_json()
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO reports
                   (peer_ip, peer_name, schema_version, collected_at, received_at, report_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    peer_ip,
                    peer_name,
                    report.schema_version,
                    report.collected_at.astimezone(UTC).isoformat(),
                    received_at.astimezone(UTC).isoformat(),
                    payload,
                ),
            )
            connection.execute("DELETE FROM reports WHERE received_at < ?", (cutoff.astimezone(UTC).isoformat(),))
            connection.commit()
            return int(cursor.lastrowid)

    def latest_reports(self) -> dict[str, dict[str, object]]:
        query = """
            SELECT id, peer_name, collected_at, received_at, report_json
            FROM reports AS report
            WHERE id = (
                SELECT id FROM reports AS newest
                WHERE newest.peer_name = report.peer_name
                ORDER BY newest.received_at DESC, newest.id DESC
                LIMIT 1
            )
        """
        with self.connect() as connection:
            rows = connection.execute(query).fetchall()
        return {
            str(row["peer_name"]): {
                "id": row["id"],
                "collected_at": row["collected_at"],
                "received_at": row["received_at"],
                "report": json.loads(row["report_json"]),
            }
            for row in rows
        }

