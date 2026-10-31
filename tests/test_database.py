from datetime import datetime, timedelta
from pathlib import Path

from homelab_status.database import Database
from homelab_status.models import StatusReport


def test_latest_report_survives_new_database_instance(
    tmp_path: Path, now: datetime, report: StatusReport
) -> None:
    path = tmp_path / "status.sqlite3"
    database = Database(path)
    database.initialize()
    database.insert_report("u59", "10.0.1.2", report, now - timedelta(minutes=2))
    newer = report.model_copy(update={"uptime_seconds": report.uptime_seconds + 60})
    database.insert_report("u59", "10.0.1.2", newer, now)

    reopened = Database(path)
    latest = reopened.latest_reports()

    assert latest["u59"]["report"]["uptime_seconds"] == 90_060


def test_insert_prunes_reports_older_than_retention(
    tmp_path: Path, now: datetime, report: StatusReport
) -> None:
    database = Database(tmp_path / "status.sqlite3", retention_days=30)
    database.initialize()
    database.insert_report("u59", "10.0.1.2", report, now - timedelta(days=31))
    database.insert_report("awesom", "10.0.1.1", report, now)

    assert set(database.latest_reports()) == {"awesom"}

