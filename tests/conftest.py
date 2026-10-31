from __future__ import annotations

from datetime import UTC, datetime

import pytest

from homelab_status.models import StatusReport


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


@pytest.fixture
def report(now: datetime) -> StatusReport:
    return StatusReport.model_validate(
        {
            "schema_version": 1,
            "collected_at": now.isoformat(),
            "uptime_seconds": 90_000,
            "reboot_required": False,
            "os_version": "Debian GNU/Linux 13 (trixie)",
            "kernel_version": "6.12.43+deb13-amd64",
            "load_average": [0.12, 0.18, 0.22],
            "memory_available_bytes": 4_000_000_000,
            "memory_total_bytes": 8_000_000_000,
            "disks": [
                {
                    "mount_point": "/",
                    "total_bytes": 1000,
                    "used_bytes": 400,
                    "available_bytes": 600,
                }
            ],
            "restic_backups": [],
        }
    )

