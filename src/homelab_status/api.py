from __future__ import annotations

import logging
import hashlib
import json
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from .config import Settings, load_settings
from .database import Database
from .models import StatusReport
from .quote import DailyQuoteCache
from .rendering import render_framebuffer, render_png
from .service import status_snapshot
from .tablet_rendering import render_tablet_png
from .wallpaper import WallpaperCache, WikimediaPictureOfDayCache
from .weather import WeatherClient
from .weather_icons import MeteoconsCache

logger = logging.getLogger("homelab_status")


def error_response(status: int, code: str, message: str, details: Any = None) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return JSONResponse(status_code=status, content={"error": error})


def create_app(settings: Settings | None = None) -> FastAPI:
    configured = settings or load_settings()
    database = Database(configured.database_path, configured.retention_days)
    database.initialize()
    weather = (
        WeatherClient(
            configured.weather_latitude,
            configured.weather_longitude,
            configured.weather_location_name,
            configured.weather_cache_seconds,
            configured.weather_timeout_seconds,
        )
        if configured.weather_enabled
        else None
    )
    fallback_wallpaper = (
        WallpaperCache(
            configured.wallpaper_cache_dir,
            configured.wallpaper_url_template,
            configured.tablet_width,
            configured.tablet_height,
            configured.wallpaper_timeout_seconds,
            configured.wallpaper_max_bytes,
        )
        if configured.tablet_enabled and configured.wallpaper_enabled
        else None
    )
    wallpaper = (
        WikimediaPictureOfDayCache(
            configured.wallpaper_cache_dir,
            configured.tablet_width,
            configured.tablet_height,
            fallback_wallpaper,
            configured.wallpaper_timeout_seconds,
            configured.wallpaper_max_bytes,
        )
        if fallback_wallpaper and configured.wallpaper_provider == "wikimedia"
        else fallback_wallpaper
    )
    daily_quote = (
        DailyQuoteCache(
            configured.quote_cache_path,
            configured.quote_of_the_day_url,
            configured.quote,
            configured.quote_timeout_seconds,
        )
        if configured.quote_of_the_day_enabled
        else None
    )
    weather_icons = (
        MeteoconsCache(
            configured.weather_icon_cache_dir,
            configured.weather_icon_url_template,
            configured.weather_icon_timeout_seconds,
        )
        if configured.tablet_enabled and configured.weather_icons_enabled
        else None
    )
    tablet_cache: dict[str, Any] = {}
    tablet_cache_lock = threading.Lock()
    app = FastAPI(title="Homelab Status", version="0.1.0", docs_url=None, redoc_url=None)
    app.state.settings = configured
    app.state.database = database
    app.state.wallpaper = wallpaper
    app.state.daily_quote = daily_quote
    app.state.weather_icons = weather_icons

    @app.post("/status", status_code=202)
    async def ingest(request: Request) -> Response:
        source_ip = request.client.host if request.client else ""
        peer = configured.peers_by_ip.get(source_ip)
        if peer is None:
            logger.warning("status_rejected", extra={"source_ip": source_ip, "reason": "unknown_peer"})
            return error_response(403, "unknown_peer", "The source address is not configured.")
        content_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
        if content_type != "application/json":
            return error_response(415, "unsupported_media_type", "Content-Type must be application/json.")
        content_length = request.headers.get("content-length")
        if content_length and (not content_length.isdigit() or int(content_length) > configured.max_request_bytes):
            return error_response(413, "request_too_large", "The status report exceeds the size limit.")
        chunks: list[bytes] = []
        received_bytes = 0
        async for chunk in request.stream():
            received_bytes += len(chunk)
            if received_bytes > configured.max_request_bytes:
                return error_response(413, "request_too_large", "The status report exceeds the size limit.")
            chunks.append(chunk)
        body = b"".join(chunks)
        try:
            report = StatusReport.model_validate_json(body)
        except ValidationError as exc:
            return error_response(
                422,
                "invalid_report",
                "The status report is invalid.",
                exc.errors(include_url=False, include_context=False),
            )
        received_at = datetime.now(UTC)
        if report.collected_at.astimezone(UTC) > received_at + timedelta(seconds=configured.future_clock_skew_seconds):
            return error_response(422, "future_timestamp", "collected_at is too far in the future.")
        database.insert_report(peer.name, source_ip, report, received_at)
        logger.info("status_accepted", extra={"peer": peer.name, "bytes": len(body)})
        return JSONResponse(
            status_code=202,
            content={"accepted": True, "peer": peer.name, "received_at": received_at.isoformat()},
        )

    @app.get("/status")
    async def get_status() -> dict[str, object]:
        return status_snapshot(configured, database)

    async def monochrome_data() -> tuple[dict[str, Any], str]:
        snapshot = status_snapshot(configured, database)
        snapshot["weather"] = await run_in_threadpool(weather.get) if weather else None
        local_day = datetime.now(ZoneInfo(configured.dashboard_timezone)).date()
        quote_text = daily_quote.get(local_day).display() if daily_quote else configured.quote
        return snapshot, quote_text

    @app.get("/dashboard/bw.png")
    async def dashboard_png() -> Response:
        snapshot, quote_text = await monochrome_data()
        content = render_png(
            snapshot,
            timezone=configured.dashboard_timezone,
            quote=quote_text,
            backup_stale_after_hours=configured.backup_stale_after_hours,
        )
        return Response(
            content=content,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=30"},
        )

    @app.get("/dashboard/bw.bin")
    async def dashboard_bin() -> Response:
        snapshot, quote_text = await monochrome_data()
        content = render_framebuffer(
            snapshot,
            timezone=configured.dashboard_timezone,
            quote=quote_text,
            backup_stale_after_hours=configured.backup_stale_after_hours,
        )
        return Response(
            content=content,
            media_type="application/octet-stream",
            headers={"Cache-Control": "public, max-age=30"},
        )

    @app.get("/dashboard/color.png")
    async def tablet_dashboard_png(request: Request) -> Response:
        if not configured.tablet_enabled:
            return error_response(404, "tablet_disabled", "The tablet dashboard is disabled.")
        snapshot = status_snapshot(configured, database)
        current_weather = await run_in_threadpool(weather.get) if weather else None
        snapshot["weather"] = current_weather
        weather_icon = (
            weather_icons.get(str(current_weather["condition"]))
            if weather_icons and current_weather
            else None
        )
        local_day = datetime.now(ZoneInfo(configured.dashboard_timezone)).date()
        quote_text = daily_quote.get(local_day).display() if daily_quote else configured.quote
        bucket = int(time.time() // max(1, configured.tablet_cache_seconds))
        key_data = {
            "bucket": bucket,
            "reports": [(peer["name"], peer["received_at"]) for peer in snapshot["peers"]],
            "weather": current_weather,
            "quote": quote_text,
            "width": configured.tablet_width,
            "height": configured.tablet_height,
        }
        cache_key = json.dumps(key_data, sort_keys=True, separators=(",", ":"), default=str)

        def build() -> tuple[bytes, str]:
            with tablet_cache_lock:
                if tablet_cache.get("key") == cache_key:
                    return tablet_cache["content"], tablet_cache["etag"]
                asset = wallpaper.get_asset(local_day) if wallpaper else None
                content = render_tablet_png(
                    snapshot,
                    asset.image if asset else None,
                    width=configured.tablet_width,
                    height=configured.tablet_height,
                    timezone=configured.dashboard_timezone,
                    backup_stale_after_hours=configured.backup_stale_after_hours,
                    quote=quote_text,
                    background_description=asset.description if asset else None,
                    weather_icon=weather_icon,
                )
                etag = f'"{hashlib.sha256(content).hexdigest()}"'
                tablet_cache.update(key=cache_key, content=content, etag=etag)
                return content, etag

        # A cache miss renders once per configured interval; cache hits are immediate.
        # Keeping this call local also avoids nested framework threadpool behavior.
        content, etag = build()
        headers = {
            "Cache-Control": f"public, max-age={configured.tablet_cache_seconds}, stale-if-error=86400",
            "ETag": etag,
        }
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)
        return Response(content=content, media_type="image/png", headers=headers)

    return app

