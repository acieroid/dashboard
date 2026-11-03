from datetime import datetime
from io import BytesIO

from PIL import Image

from homelab_status.rendering import (
    HEIGHT,
    WIDTH,
    _compact_system_identity,
    render_dashboard,
    render_png,
)


def test_compacts_debian_and_kernel_identity() -> None:
    assert _compact_system_identity(
        {
            "os_version": "Debian GNU/Linux 12 (bookworm)",
            "kernel_version": "6.1.0-31-amd64",
        }
    ) == "Debian 12 (6.1.0…)"


def sample_snapshot(now: datetime) -> dict[str, object]:
    return {
        "generated_at": now.isoformat(),
        "weather": {
            "location": "Brussels",
            "temperature_c": 9.4,
            "condition": "Partly cloudy",
            "forecast_condition": "Rain",
            "minimum_c": 5.2,
            "maximum_c": 11.8,
            "precipitation_probability": 70,
        },
        "peers": [
            {
                "name": "u59",
                "state": "fresh",
                "age_seconds": 10,
                "received_at": now.isoformat(),
                "report": {
                    "uptime_seconds": 90_000,
                    "reboot_required": True,
                    "os_version": "Debian GNU/Linux 12 (bookworm)",
                    "kernel_version": "6.1.0-31-amd64",
                    "load_average": [0.12, 0.18, 0.22],
                    "memory_available_bytes": 4_000_000_000,
                    "memory_total_bytes": 8_000_000_000,
                    "disks": [
                        {
                            "mount_point": "/srv/data",
                            "total_bytes": 1000,
                            "used_bytes": 720,
                            "available_bytes": 280,
                        }
                    ],
                    "restic_backups": [
                        {
                            "repository": "primary",
                            "snapshot_time": now.isoformat(),
                            "last_run_successful": True,
                        }
                    ],
                },
            },
            {"name": "latitude", "state": "missing", "report": None},
        ],
    }


def test_dashboard_is_monochrome_400_by_300(now: datetime) -> None:
    image = render_dashboard(sample_snapshot(now))
    assert image.mode == "1"
    assert image.size == (WIDTH, HEIGHT) == (400, 300)
    assert image.getbbox() == (0, 0, 400, 300)


def test_png_round_trip(now: datetime) -> None:
    content = render_png(sample_snapshot(now), timezone="Europe/Brussels", quote="Keep going.")
    image = Image.open(BytesIO(content))
    assert image.format == "PNG"
    assert image.mode == "1"
    assert image.size == (400, 300)

