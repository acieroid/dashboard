from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO

from PIL import Image

from homelab_status.tablet_rendering import render_tablet_dashboard, render_tablet_png


def snapshot() -> dict[str, object]:
    now = datetime(2026, 10, 29, 8, 24, tzinfo=UTC)
    report = {
        "uptime_seconds": 1_245_600,
        "reboot_required": False,
        "os_version": "Debian GNU/Linux 13 (trixie)",
        "kernel_version": "6.12.43+deb13-amd64",
        "load_average": [0.18, 0.24, 0.31],
        "memory_available_bytes": 6 * 1024**3,
        "memory_total_bytes": 16 * 1024**3,
        "disks": [
            {
                "mount_point": "/",
                "total_bytes": 476 * 1024**3,
                "used_bytes": 194 * 1024**3,
                "available_bytes": 282 * 1024**3,
            }
        ],
        "restic_backups": [
            {
                "repository": "primary",
                "snapshot_time": (now - timedelta(hours=8)).isoformat(),
                "data_added_bytes": 700 * 1024**2,
                "last_run_successful": True,
            }
        ],
    }
    return {
        "generated_at": now.isoformat(),
        "weather": {
            "location": "Brussels",
            "temperature_c": 11.0,
            "condition": "Light rain",
            "minimum_c": 7.0,
            "maximum_c": 13.0,
            "precipitation_probability": 70,
            "forecast": [
                {"date": "2026-10-29", "minimum_c": 7, "maximum_c": 13, "precipitation_probability": 70},
                {"date": "2026-10-30", "minimum_c": 6, "maximum_c": 12, "precipitation_probability": 40},
                {"date": "2026-10-31", "minimum_c": 8, "maximum_c": 14, "precipitation_probability": 20},
                {"date": "2026-11-01", "minimum_c": 7, "maximum_c": 11, "precipitation_probability": 60},
            ],
        },
        "peers": [
            {"name": "awesom", "state": "fresh", "age_seconds": 120, "report": report},
            {"name": "u59", "state": "stale", "age_seconds": 2_700, "report": report | {"reboot_required": True}},
            {"name": "localhost", "state": "missing", "age_seconds": 9_000, "report": report},
        ],
    }


def test_renders_widget_on_bright_and_dark_backgrounds() -> None:
    for color in ((238, 230, 210), (20, 28, 38)):
        image = render_tablet_dashboard(
            snapshot(),
            Image.new("RGB", (1200, 1800), color),
            quote="Make each day useful. — Anonymous",
            background_description="Morning light over a quiet mountain valley",
            weather_icon=Image.new("RGBA", (64, 64), (250, 190, 50, 255)),
        )
        assert image.mode == "RGB"
        assert image.size == (500, 500)


def test_renders_reduced_widget_resolution() -> None:
    content = render_tablet_png(
        snapshot(),
        Image.new("RGB", (1920, 1200), (40, 80, 100)),
        width=400,
        height=400,
        timezone="Europe/Brussels",
    )
    image = Image.open(BytesIO(content))
    assert image.format == "PNG"
    assert image.size == (400, 400)
