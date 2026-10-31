from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from homelab_status.models import StatusReport


def test_rejects_duplicate_mount_points(now: datetime) -> None:
    payload = {
        "collected_at": now.isoformat(),
        "uptime_seconds": 1,
        "disks": [
            {"mount_point": "/", "total_bytes": 10, "used_bytes": 1, "available_bytes": 9},
            {"mount_point": "/", "total_bytes": 10, "used_bytes": 2, "available_bytes": 8},
        ],
    }
    with pytest.raises(ValidationError, match="mount points must be unique"):
        StatusReport.model_validate(payload)


def test_rejects_timestamp_without_timezone() -> None:
    with pytest.raises(ValidationError, match="must include a timezone"):
        StatusReport.model_validate(
            {"collected_at": datetime(2026, 1, 1).isoformat(), "uptime_seconds": 1}
        )


def test_nullable_reboot_state(now: datetime) -> None:
    report = StatusReport.model_validate(
        {"collected_at": now.astimezone(UTC).isoformat(), "uptime_seconds": 1, "reboot_required": None}
    )
    assert report.reboot_required is None


def test_rejects_impossible_memory_values(now: datetime) -> None:
    with pytest.raises(ValidationError, match="available memory cannot exceed total memory"):
        StatusReport.model_validate(
            {
                "collected_at": now.isoformat(),
                "uptime_seconds": 1,
                "memory_available_bytes": 11,
                "memory_total_bytes": 10,
            }
        )


def test_accepts_explicit_failed_backup(now: datetime) -> None:
    report = StatusReport.model_validate(
        {
            "collected_at": now.isoformat(),
            "uptime_seconds": 1,
            "restic_backups": [
                {
                    "repository": "primary",
                    "snapshot_time": now.isoformat(),
                    "last_run_successful": False,
                }
            ],
        }
    )
    assert report.restic_backups[0].last_run_successful is False

