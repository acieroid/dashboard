from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

from homelab_status.config import load_settings
from homelab_status.database import Database
from homelab_status.models import StatusReport


SAMPLES = {
    "awesom": {"uptime_seconds": 1_245_600, "reboot_required": False, "disk": (512_000_000_000, 194_000_000_000)},
    "u59": {"uptime_seconds": 432_000, "reboot_required": True, "disk": (8_000_000_000_000, 5_630_000_000_000)},
    "latitude": {"uptime_seconds": 93_600, "reboot_required": None, "disk": (1_000_000_000_000, 412_000_000_000)},
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Insert sample dashboard reports")
    parser.add_argument("--config", default="config.toml")
    args = parser.parse_args()
    settings = load_settings(args.config)
    database = Database(settings.database_path, settings.retention_days)
    database.initialize()
    now = datetime.now(UTC)
    for peer in settings.peers:
        sample = SAMPLES.get(peer.name)
        if sample is None:
            continue
        total, used = sample["disk"]
        report = StatusReport.model_validate(
            {
                "schema_version": 1,
                "collected_at": now.isoformat(),
                "uptime_seconds": sample["uptime_seconds"],
                "reboot_required": sample["reboot_required"],
                "load_average": [0.18, 0.24, 0.31],
                "memory_available_bytes": 6_442_450_944,
                "memory_total_bytes": 17_179_869_184,
                "disks": [{"mount_point": "/", "total_bytes": total, "used_bytes": used, "available_bytes": total - used}],
                "restic_backups": [{"repository": "primary", "snapshot_time": (now - timedelta(hours=6)).isoformat(), "data_added_bytes": 734_003_200, "last_run_successful": True}],
            }
        )
        database.insert_report(peer.name, peer.wireguard_ip, report, now)


if __name__ == "__main__":
    main()

