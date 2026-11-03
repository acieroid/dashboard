from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from homelab_status.collector import (
    ResticConfig,
    collect_status,
    load_collector_config,
    read_disks,
    read_os_version,
    read_memory,
    read_restic_backup,
    read_uptime,
    run,
    status_url,
    submit_status,
)


def test_reads_linux_uptime(tmp_path: Path) -> None:
    uptime = tmp_path / "uptime"
    uptime.write_text("91823.75 120000.00\n", encoding="ascii")
    assert read_uptime(uptime) == 91823


def test_reads_available_and_total_memory(tmp_path: Path) -> None:
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(
        "MemTotal:       16384000 kB\nMemFree:         1000000 kB\nMemAvailable:    8000000 kB\n",
        encoding="ascii",
    )
    assert read_memory(meminfo) == (8_192_000_000, 16_777_216_000)


def test_reads_pretty_os_version(tmp_path: Path) -> None:
    os_release = tmp_path / "os-release"
    os_release.write_text(
        'PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\nNAME="Debian GNU/Linux"\nVERSION_ID="13"\n',
        encoding="utf-8",
    )
    assert read_os_version(os_release) == "Debian GNU/Linux 13 (trixie)"


@pytest.mark.parametrize(
    ("provided", "expected"),
    [
        ("http://10.0.1.1:8080", "http://10.0.1.1:8080/status"),
        ("http://10.0.1.1:8080/", "http://10.0.1.1:8080/status"),
        ("https://status.example/status", "https://status.example/status"),
    ],
)
def test_normalizes_status_url(provided: str, expected: str) -> None:
    assert status_url(provided) == expected


def test_submit_sends_compact_json(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self) -> bytes:
            return b'{"accepted":true,"peer":"u59"}'

    def open_request(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", open_request)
    response = submit_status("http://10.0.1.1:8080", {"schema_version": 1}, 3.0)

    request = captured["request"]
    assert request.full_url == "http://10.0.1.1:8080/status"
    assert request.get_method() == "POST"
    assert json.loads(request.data) == {"schema_version": 1}
    assert captured["timeout"] == 3.0
    assert response == {"accepted": True, "peer": "u59"}


def test_loads_mounts_and_multiple_restic_options(tmp_path: Path) -> None:
    config_path = tmp_path / "collector.toml"
    config_path.write_text(
        '''
mount_points = ["/", "/srv/data"]
[[restic]]
label = "primary"
repository = "/backup/repo"
password_file = "/etc/restic/password"
result_file = "/run/restic-result.json"
timeout_seconds = 12
''',
        encoding="utf-8",
    )

    config = load_collector_config(config_path)

    assert config.mount_points == ("/", "/srv/data")
    assert config.restic == (
        ResticConfig(
            label="primary",
            repository="/backup/repo",
            password_file=Path("/etc/restic/password"),
            result_file=Path("/run/restic-result.json"),
            timeout_seconds=12,
        ),
    )


def test_rejects_duplicate_restic_labels(tmp_path: Path) -> None:
    config_path = tmp_path / "collector.toml"
    config_path.write_text('[[restic]]\nlabel="same"\n[[restic]]\nlabel="same"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="labels must be unique"):
        load_collector_config(config_path)


def test_omits_unavailable_disk_without_losing_other_disks(monkeypatch: pytest.MonkeyPatch) -> None:
    usage = type("Usage", (), {"total": 100, "used": 60, "free": 40})()

    def disk_usage(path):
        if path == "/missing":
            raise FileNotFoundError(path)
        return usage

    warnings = []
    monkeypatch.setattr("shutil.disk_usage", disk_usage)
    disks = read_disks(["/", "/missing"], warnings.append)

    assert disks == [{"mount_point": "/", "total_bytes": 100, "used_bytes": 60, "available_bytes": 40}]
    assert "'/missing' omitted" in warnings[0]


def test_reads_latest_restic_snapshot_and_result_marker(tmp_path: Path) -> None:
    marker = tmp_path / "result.json"
    marker.write_text('{"successful":true,"data_added_bytes":734003200}', encoding="utf-8")
    captured = {}

    def runner(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='[{"time":"2026-10-30T01:02:03Z","short_id":"abc123"}]',
            stderr="",
        )

    backup = read_restic_backup(
        ResticConfig(
            label="primary",
            repository="/backup/repo",
            password_file=Path("/secret/password"),
            result_file=marker,
            timeout_seconds=7,
        ),
        runner=runner,
    )

    assert captured["command"] == [
        "restic", "--repo", "/backup/repo", "--password-file", "/secret/password",
        "--no-cache", "--no-lock", "snapshots", "--latest", "1", "--json",
    ]
    assert captured["kwargs"]["timeout"] == 7
    assert backup == {
        "repository": "primary",
        "snapshot_time": "2026-10-30T01:02:03Z",
        "snapshot_id": "abc123",
        "data_added_bytes": 734003200,
        "last_run_successful": True,
    }


def test_bad_result_marker_does_not_hide_valid_snapshot(tmp_path: Path) -> None:
    marker = tmp_path / "result.json"
    marker.write_text("not json", encoding="utf-8")
    warnings = []

    def runner(command, **kwargs):
        return subprocess.CompletedProcess(
            command, 0, stdout='[{"time":"2026-10-30T01:02:03Z","id":"full-id"}]', stderr=""
        )

    backup = read_restic_backup(ResticConfig(label="primary", result_file=marker), runner, warnings.append)

    assert backup["snapshot_id"] == "full-id"
    assert "last_run_successful" not in backup
    assert "result marker ignored" in warnings[0]


def test_uses_snapshot_summary_bytes_and_applies_filters() -> None:
    captured = {}

    def runner(command, **kwargs):
        captured["command"] = command
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                '[{"time":"2026-10-30T01:02:03Z","id":"id",'
                '"summary":{"data_added":4096}}]'
            ),
            stderr="",
        )

    backup = read_restic_backup(
        ResticConfig(
            label="daily",
            snapshot_host="u59",
            snapshot_tags=("daily",),
            snapshot_paths=("/srv/data",),
        ),
        runner,
    )

    assert captured["command"][-12:] == [
        "--no-cache", "--no-lock", "snapshots", "--host", "u59", "--tag", "daily", "--path", "/srv/data",
        "--latest", "1", "--json",
    ]
    assert backup["data_added_bytes"] == 4096
    assert "last_run_successful" not in backup


def test_selects_newest_snapshot_when_latest_returns_multiple_groups() -> None:
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                '[{"time":"2025-06-20T04:53:28-04:00","id":"old"},'
                '{"time":"2026-10-26T05:00:01-04:00","id":"new",'
                '"summary":{"data_added":1221992536}}]'
            ),
            stderr="",
        )

    backup = read_restic_backup(ResticConfig(label="primary"), runner)

    assert backup["snapshot_id"] == "new"
    assert backup["snapshot_time"] == "2026-10-26T05:00:01-04:00"
    assert backup["data_added_bytes"] == 1221992536


def test_reads_restic_json_lines_summary_marker(tmp_path: Path) -> None:
    marker = tmp_path / "backup.jsonl"
    marker.write_text(
        '{"message_type":"status","percent_done":0.5}\n'
        '{"message_type":"summary","data_added":8192,"error_count":0}\n',
        encoding="utf-8",
    )

    def runner(command, **kwargs):
        return subprocess.CompletedProcess(
            command, 0, stdout='[{"time":"2026-10-30T01:02:03Z","id":"id"}]', stderr=""
        )

    backup = read_restic_backup(ResticConfig(label="primary", result_file=marker), runner)

    assert backup["data_added_bytes"] == 8192
    assert backup["last_run_successful"] is True


def test_optional_restic_failure_does_not_abort_report(monkeypatch: pytest.MonkeyPatch) -> None:
    warnings = []
    monkeypatch.setattr("homelab_status.collector.read_disks", lambda mounts, warn: [])
    monkeypatch.setattr(
        "homelab_status.collector.read_restic_backup",
        lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("restic", 2)),
    )

    report = collect_status(["/"], [ResticConfig(label="slow")], warnings.append)

    assert report["restic_backups"] == []
    assert "Restic 'slow' omitted" in warnings[0]


def test_cli_rejects_invalid_success_response(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr("homelab_status.collector.collect_status", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr("homelab_status.collector.submit_status", lambda *args, **kwargs: {"peer": "u59"})

    assert run(["u59", "http://10.0.1.1:8080/status"]) == 1
    assert "invalid acceptance response" in capsys.readouterr().err
