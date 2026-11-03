from __future__ import annotations

import argparse
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Sequence

DEFAULT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class ResticConfig:
    label: str
    repository: str | None = None
    password_file: Path | None = None
    result_file: Path | None = None
    snapshot_host: str | None = None
    snapshot_tags: tuple[str, ...] = ()
    snapshot_paths: tuple[str, ...] = ()
    timeout_seconds: float = 20.0
    executable: str = "restic"


@dataclass(frozen=True, slots=True)
class CollectorConfig:
    mount_points: tuple[str, ...] = ("/",)
    restic: tuple[ResticConfig, ...] = ()


def load_collector_config(path: Path) -> CollectorConfig:
    with path.open("rb") as stream:
        payload = tomllib.load(stream)
    allowed = {"mount_points", "restic"}
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"unknown collector config keys: {', '.join(sorted(unknown))}")
    mount_values = payload.get("mount_points", ["/"])
    if not isinstance(mount_values, list):
        raise ValueError("mount_points must be a list")
    mounts = tuple(str(value) for value in mount_values)
    if not mounts or len(mounts) > 16 or any(not value for value in mounts) or len(set(mounts)) != len(mounts):
        raise ValueError("mount_points must be a non-empty list of unique paths")
    restic_items: list[ResticConfig] = []
    for item in payload.get("restic", []):
        if not isinstance(item, dict):
            raise ValueError("each restic entry must be a table")
        item_unknown = set(item) - {
            "label", "repository", "password_file", "result_file", "snapshot_host",
            "snapshot_tags", "snapshot_paths", "timeout_seconds", "executable"
        }
        if item_unknown:
            raise ValueError(f"unknown restic config keys: {', '.join(sorted(item_unknown))}")
        label = str(item["label"])
        timeout = float(item.get("timeout_seconds", 20.0))
        tag_values = item.get("snapshot_tags", [])
        path_values = item.get("snapshot_paths", [])
        if not isinstance(tag_values, list) or not isinstance(path_values, list):
            raise ValueError("snapshot_tags and snapshot_paths must be lists")
        if not label or len(label) > 64 or timeout <= 0:
            raise ValueError("restic label must be 1-64 characters and timeout_seconds must be positive")
        restic_items.append(
            ResticConfig(
                label=label,
                repository=str(item["repository"]) if item.get("repository") else None,
                password_file=Path(str(item["password_file"])) if item.get("password_file") else None,
                result_file=Path(str(item["result_file"])) if item.get("result_file") else None,
                snapshot_host=str(item["snapshot_host"]) if item.get("snapshot_host") else None,
                snapshot_tags=tuple(str(value) for value in tag_values),
                snapshot_paths=tuple(str(value) for value in path_values),
                timeout_seconds=timeout,
                executable=str(item.get("executable", "restic")),
            )
        )
    labels = [item.label for item in restic_items]
    if len(restic_items) > 16:
        raise ValueError("at most 16 restic repositories may be configured")
    if len(labels) != len(set(labels)):
        raise ValueError("restic labels must be unique")
    return CollectorConfig(mounts, tuple(restic_items))


def read_uptime(path: Path = Path("/proc/uptime")) -> int:
    value = path.read_text(encoding="ascii").split(maxsplit=1)[0]
    return max(0, int(float(value)))


def reboot_required(path: Path = Path("/var/run/reboot-required")) -> bool | None:
    try:
        return path.exists()
    except OSError:
        return None


def read_load_average() -> tuple[float, float, float] | None:
    try:
        one, five, fifteen = os.getloadavg()
    except (AttributeError, OSError):
        return None
    return one, five, fifteen


def read_os_version(path: Path = Path("/etc/os-release")) -> str | None:
    try:
        values: dict[str, str] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            key, separator, raw_value = line.partition("=")
            if not separator or key not in {"PRETTY_NAME", "NAME", "VERSION_ID"}:
                continue
            parsed = shlex.split(raw_value, comments=False, posix=True)
            values[key] = parsed[0] if parsed else ""
        pretty = values.get("PRETTY_NAME")
        if pretty:
            return pretty[:128]
        fallback = " ".join(part for part in (values.get("NAME"), values.get("VERSION_ID")) if part)
        return fallback[:128] or None
    except (OSError, ValueError):
        return None


def read_kernel_version() -> str | None:
    try:
        value = platform.release().strip()
        return value[:128] or None
    except OSError:
        return None


def read_memory(path: Path = Path("/proc/meminfo")) -> tuple[int, int] | None:
    try:
        values: dict[str, int] = {}
        for line in path.read_text(encoding="ascii").splitlines():
            key, separator, remainder = line.partition(":")
            if separator and key in {"MemTotal", "MemAvailable", "MemFree"}:
                values[key] = int(remainder.strip().split()[0]) * 1024
        total = values["MemTotal"]
        available = values.get("MemAvailable", values.get("MemFree"))
        if available is None:
            return None
        return available, total
    except (OSError, KeyError, ValueError, IndexError):
        return None


def read_disks(
    mount_points: Sequence[str],
    warn: Callable[[str], None] | None = None,
) -> list[dict[str, int | str]]:
    disks: list[dict[str, int | str]] = []
    for mount_point in mount_points:
        try:
            usage = shutil.disk_usage(mount_point)
        except (OSError, ValueError) as exc:
            if warn:
                warn(f"disk {mount_point!r} omitted: {exc}")
            continue
        disks.append(
            {
                "mount_point": mount_point,
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "available_bytes": usage.free,
            }
        )
    return disks


def _backup_result(path: Path | None) -> tuple[bool | None, int | None]:
    if path is None:
        return None, None
    text = path.read_text(encoding="utf-8")
    try:
        values = [json.loads(line) for line in text.splitlines() if line.strip()]
    except json.JSONDecodeError:
        values = [json.loads(text)]
    if not values:
        raise ValueError("backup result file is empty")
    value = values[-1]
    if not isinstance(value, dict):
        raise ValueError("backup result must be a JSON object")
    if value.get("message_type") == "summary":
        successful: bool | None = not bool(value.get("error_count", 0))
        added = value.get("data_added")
    else:
        successful = value.get("successful")
        added = value.get("data_added_bytes")
    if successful is not None and not isinstance(successful, bool):
        raise ValueError("backup result successful must be boolean or null")
    if added is not None and (not isinstance(added, int) or isinstance(added, bool) or added < 0):
        raise ValueError("backup result changed bytes must be a non-negative integer or null")
    return successful, added


def read_restic_backup(
    config: ResticConfig,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    warn: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    command = [config.executable]
    if config.repository:
        command.extend(["--repo", config.repository])
    if config.password_file:
        command.extend(["--password-file", str(config.password_file)])
    command.extend(["--no-cache", "--no-lock", "snapshots"])
    if config.snapshot_host:
        command.extend(["--host", config.snapshot_host])
    for tag in config.snapshot_tags:
        command.extend(["--tag", tag])
    for path in config.snapshot_paths:
        command.extend(["--path", path])
    command.extend(["--latest", "1", "--json"])
    result = runner(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=config.timeout_seconds,
        env=os.environ.copy(),
    )
    snapshots = json.loads(result.stdout)
    if not isinstance(snapshots, list) or not snapshots:
        raise ValueError("Restic repository contains no snapshots")
    valid_snapshots = [
        item for item in snapshots if isinstance(item, dict) and item.get("time")
    ]
    if not valid_snapshots:
        raise ValueError("Restic returned an invalid snapshot")
    try:
        snapshot = max(
            valid_snapshots,
            key=lambda item: datetime.fromisoformat(str(item["time"]).replace("Z", "+00:00")),
        )
    except ValueError as exc:
        raise ValueError("Restic returned an invalid snapshot timestamp") from exc
    summary = snapshot.get("summary")
    snapshot_added = summary.get("data_added") if isinstance(summary, dict) else None
    if snapshot_added is not None and (
        not isinstance(snapshot_added, int) or isinstance(snapshot_added, bool) or snapshot_added < 0
    ):
        snapshot_added = None
    try:
        successful, marker_added = _backup_result(config.result_file)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        successful, marker_added = None, None
        if warn:
            warn(f"Restic {config.label!r} result marker ignored: {exc}")
    backup: dict[str, Any] = {
        "repository": config.label,
        "snapshot_time": str(snapshot["time"]),
    }
    snapshot_id = snapshot.get("short_id") or snapshot.get("id")
    if snapshot_id:
        backup["snapshot_id"] = str(snapshot_id)[:64]
    added = marker_added if marker_added is not None else snapshot_added
    if added is not None:
        backup["data_added_bytes"] = added
    if successful is not None:
        backup["last_run_successful"] = successful
    return backup


def collect_status(
    mount_points: Sequence[str],
    restic_configs: Sequence[ResticConfig] = (),
    warn: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    memory = read_memory()
    report: dict[str, Any] = {
        "schema_version": 1,
        "collected_at": datetime.now(UTC).isoformat(),
        "uptime_seconds": read_uptime(),
        "reboot_required": reboot_required(),
        "disks": read_disks(mount_points, warn),
        "restic_backups": [],
    }
    load = read_load_average()
    if load is not None:
        report["load_average"] = list(load)
    os_version = read_os_version()
    if os_version:
        report["os_version"] = os_version
    kernel_version = read_kernel_version()
    if kernel_version:
        report["kernel_version"] = kernel_version
    if memory is not None:
        report["memory_available_bytes"], report["memory_total_bytes"] = memory
    for restic_config in restic_configs:
        try:
            report["restic_backups"].append(read_restic_backup(restic_config, warn=warn))
        except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
            if warn:
                warn(f"Restic {restic_config.label!r} omitted: {exc}")
    return report


def status_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("URL must be an absolute http:// or https:// URL")
    path = parsed.path.rstrip("/")
    if not path:
        path = "/status"
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, ""))


def submit_status(url: str, report: dict[str, Any], timeout_seconds: float) -> dict[str, Any] | None:
    body = json.dumps(report, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        status_url(url),
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "homelab-status-collector/0.1",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        response_body = response.read()
    return json.loads(response_body) if response_body else None


def parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(
        description="Collect local Linux status and push it to a homelab status service."
    )
    argument_parser.add_argument("machine_name", help="Display name used in local output only")
    argument_parser.add_argument("url", help="Status endpoint or service base URL")
    argument_parser.add_argument(
        "--config",
        type=Path,
        help="TOML file defining mount points and optional Restic repositories",
    )
    argument_parser.add_argument(
        "--mount",
        action="append",
        dest="mount_points",
        default=None,
        metavar="PATH",
        help="Mount point to report; repeat for multiple disks (default: /)",
    )
    argument_parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        metavar="SECONDS",
        help="HTTP timeout (default: 10)",
    )
    argument_parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print the collected JSON without sending it",
    )
    return argument_parser


def run(arguments: Sequence[str] | None = None) -> int:
    args = parser().parse_args(arguments)
    if args.timeout <= 0:
        print("error: --timeout must be positive", file=sys.stderr)
        return 2
    try:
        configured = load_collector_config(args.config) if args.config else CollectorConfig()
        mounts = tuple(args.mount_points) if args.mount_points else configured.mount_points
        report = collect_status(
            mounts,
            configured.restic,
            warn=lambda message: print(f"{args.machine_name}: warning: {message}", file=sys.stderr),
        )
    except (OSError, ValueError) as exc:
        print(f"{args.machine_name}: collection failed: {exc}", file=sys.stderr)
        return 1

    if args.print_only:
        print(json.dumps(report, indent=2))
        return 0

    try:
        response = submit_status(args.url, report, args.timeout)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"{args.machine_name}: server rejected report (HTTP {exc.code}): {detail}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"{args.machine_name}: submission failed: {exc}", file=sys.stderr)
        return 1

    if not isinstance(response, dict) or response.get("accepted") is not True or not response.get("peer"):
        print(f"{args.machine_name}: server returned an invalid acceptance response", file=sys.stderr)
        return 1
    accepted_peer = str(response["peer"])
    suffix = f" as {accepted_peer}" if accepted_peer else ""
    print(f"{args.machine_name}: status submitted{suffix}")
    if accepted_peer and accepted_peer != args.machine_name:
        print(
            f"warning: server identified this source IP as {accepted_peer}, not {args.machine_name}",
            file=sys.stderr,
        )
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
