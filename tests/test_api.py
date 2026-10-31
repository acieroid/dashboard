from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from homelab_status.api import create_app
from homelab_status.config import PeerConfig, Settings


def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "status.sqlite3",
        peers=(PeerConfig("u59", "10.0.1.2", 10),),
        weather_enabled=False,
        wallpaper_enabled=False,
        quote_of_the_day_enabled=False,
    )


def payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "collected_at": datetime.now(UTC).isoformat(),
        "uptime_seconds": 3600,
        "reboot_required": False,
        "load_average": [0.12, 0.18, 0.22],
        "memory_available_bytes": 4_000_000_000,
        "memory_total_bytes": 8_000_000_000,
        "disks": [],
        "restic_backups": [],
    }


@pytest.mark.anyio
async def test_accepts_known_source_and_renders_dashboard(tmp_path: Path) -> None:
    app = create_app(settings(tmp_path))
    transport = httpx.ASGITransport(app=app, client=("10.0.1.2", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/status", json=payload())
        assert response.status_code == 202
        assert response.json()["peer"] == "u59"

        status = (await client.get("/status")).json()
        assert status["peers"][0]["state"] == "fresh"
        assert "wireguard_ip" not in status["peers"][0]

        dashboard = await client.get("/dashboard/bw.png")
        assert dashboard.status_code == 200
        assert dashboard.headers["content-type"] == "image/png"
        assert dashboard.content.startswith(b"\x89PNG\r\n\x1a\n")

        framebuffer = await client.get("/dashboard/bw.bin")
        assert framebuffer.status_code == 200
        assert framebuffer.headers["content-type"] == "application/octet-stream"
        assert len(framebuffer.content) == 400 * 300 // 8


@pytest.mark.anyio
async def test_rejects_unknown_source_before_parsing_body(tmp_path: Path) -> None:
    app = create_app(settings(tmp_path))
    transport = httpx.ASGITransport(app=app, client=("10.0.1.99", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/status", content=b"not JSON", headers={"content-type": "application/json"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "unknown_peer"


@pytest.mark.anyio
async def test_rejects_non_json_and_oversized_reports(tmp_path: Path) -> None:
    configured = settings(tmp_path)
    configured = Settings(
        database_path=configured.database_path,
        peers=configured.peers,
        max_request_bytes=32,
    )
    app = create_app(configured)
    transport = httpx.ASGITransport(app=app, client=("10.0.1.2", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        wrong_type = await client.post("/status", content=b"{}", headers={"content-type": "text/plain"})
        oversized = await client.post("/status", content=b"{" + b"x" * 64, headers={"content-type": "application/json"})
    assert wrong_type.status_code == 415
    assert oversized.status_code == 413


@pytest.mark.anyio
async def test_tablet_dashboard_supports_conditional_requests(tmp_path: Path) -> None:
    app = create_app(settings(tmp_path))
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.get("/dashboard/color.png")
        assert first.status_code == 200
        assert first.headers["content-type"] == "image/png"
        assert first.content.startswith(b"\x89PNG\r\n\x1a\n")
        etag = first.headers["etag"]

        cached = await client.get("/dashboard/color.png", headers={"If-None-Match": etag})
        assert cached.status_code == 304
        assert cached.content == b""


@pytest.mark.anyio
async def test_legacy_dashboard_routes_are_not_exposed(tmp_path: Path) -> None:
    app = create_app(settings(tmp_path))
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/dashboard.png")).status_code == 404
        assert (await client.get("/dashboard/tablet.png")).status_code == 404

