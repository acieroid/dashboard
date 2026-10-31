from __future__ import annotations

import ipaddress
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PeerConfig:
    name: str
    wireguard_ip: str
    display_order: int


@dataclass(frozen=True, slots=True)
class Settings:
    database_path: Path
    peers: tuple[PeerConfig, ...]
    stale_after_seconds: int = 1_800
    missing_after_seconds: int = 7_200
    retention_days: int = 30
    max_request_bytes: int = 65_536
    future_clock_skew_seconds: int = 300
    dashboard_timezone: str = "Europe/Brussels"
    quote: str = "Small steps, repeated, become reliable systems."
    backup_stale_after_hours: int = 36
    quote_of_the_day_enabled: bool = True
    quote_of_the_day_url: str = "https://zenquotes.io/api/today"
    quote_cache_path: Path = Path("./data/daily-quote.json")
    quote_timeout_seconds: float = 5.0
    weather_enabled: bool = True
    weather_latitude: float = 50.8503
    weather_longitude: float = 4.3517
    weather_location_name: str = "Brussels"
    weather_cache_seconds: int = 1_800
    weather_timeout_seconds: float = 5.0
    tablet_enabled: bool = True
    tablet_width: int = 500
    tablet_height: int = 500
    tablet_cache_seconds: int = 60
    wallpaper_enabled: bool = True
    wallpaper_provider: str = "wikimedia"
    wallpaper_url_template: str = "https://picsum.photos/seed/homelab-{date}/{width}/{height}"
    wallpaper_cache_dir: Path = Path("./data/wallpapers")
    wallpaper_timeout_seconds: float = 15.0
    wallpaper_max_bytes: int = 26_214_400
    weather_icons_enabled: bool = True
    weather_icon_url_template: str = (
        "https://raw.githubusercontent.com/basmilius/meteocons/v2/"
        "production/fill/png/128/{icon}.png"
    )
    weather_icon_cache_dir: Path = Path("./data/weather-icons")
    weather_icon_timeout_seconds: float = 5.0

    @property
    def peers_by_ip(self) -> dict[str, PeerConfig]:
        return {peer.wireguard_ip: peer for peer in self.peers}


def load_settings(path: str | Path | None = None) -> Settings:
    config_path = Path(path or os.environ.get("HOMELAB_STATUS_CONFIG", "config.toml"))
    with config_path.open("rb") as stream:
        data = tomllib.load(stream)

    server = data.get("server", {})
    dashboard = data.get("dashboard", {})
    weather = data.get("weather", {})
    tablet = data.get("tablet", {})
    peers = tuple(
        PeerConfig(
            name=str(item["name"]),
            wireguard_ip=str(ipaddress.ip_address(item["wireguard_ip"])),
            display_order=int(item.get("display_order", index * 10)),
        )
        for index, item in enumerate(data.get("peers", []), start=1)
    )
    if not peers:
        raise ValueError("at least one peer must be configured")
    if len({peer.name for peer in peers}) != len(peers):
        raise ValueError("peer names must be unique")
    if len({peer.wireguard_ip for peer in peers}) != len(peers):
        raise ValueError("peer IP addresses must be unique")

    stale = int(server.get("stale_after_seconds", 1_800))
    missing = int(server.get("missing_after_seconds", 7_200))
    if stale <= 0 or missing < stale:
        raise ValueError("freshness thresholds must satisfy 0 < stale <= missing")
    backup_stale_after_hours = int(dashboard.get("backup_stale_after_hours", 36))
    if backup_stale_after_hours <= 0:
        raise ValueError("backup_stale_after_hours must be positive")
    tablet_width = int(tablet.get("width", 500))
    tablet_height = int(tablet.get("height", 500))
    if not 320 <= tablet_width <= 500 or not 320 <= tablet_height <= 500:
        raise ValueError("tablet widget dimensions must be between 320 and 500 pixels")
    wallpaper_provider = str(tablet.get("wallpaper_provider", "wikimedia"))
    if wallpaper_provider not in {"wikimedia", "url_template"}:
        raise ValueError("wallpaper_provider must be wikimedia or url_template")

    database_override = os.environ.get("HOMELAB_STATUS_DATABASE")
    return Settings(
        database_path=Path(database_override or server.get("database_path", "./data/status.sqlite3")),
        peers=tuple(sorted(peers, key=lambda peer: peer.display_order)),
        stale_after_seconds=stale,
        missing_after_seconds=missing,
        retention_days=int(server.get("retention_days", 30)),
        max_request_bytes=int(server.get("max_request_bytes", 65_536)),
        future_clock_skew_seconds=int(server.get("future_clock_skew_seconds", 300)),
        dashboard_timezone=str(dashboard.get("timezone", "Europe/Brussels")),
        quote=str(dashboard.get("quote", "Small steps, repeated, become reliable systems.")),
        backup_stale_after_hours=backup_stale_after_hours,
        quote_of_the_day_enabled=bool(dashboard.get("quote_of_the_day_enabled", True)),
        quote_of_the_day_url=str(
            dashboard.get("quote_of_the_day_url", "https://zenquotes.io/api/today")
        ),
        quote_cache_path=Path(dashboard.get("quote_cache_path", "./data/daily-quote.json")),
        quote_timeout_seconds=float(dashboard.get("quote_timeout_seconds", 5.0)),
        weather_enabled=bool(weather.get("enabled", True)),
        weather_latitude=float(weather.get("latitude", 50.8503)),
        weather_longitude=float(weather.get("longitude", 4.3517)),
        weather_location_name=str(weather.get("location_name", "Brussels")),
        weather_cache_seconds=int(weather.get("cache_seconds", 1_800)),
        weather_timeout_seconds=float(weather.get("timeout_seconds", 5.0)),
        tablet_enabled=bool(tablet.get("enabled", True)),
        tablet_width=tablet_width,
        tablet_height=tablet_height,
        tablet_cache_seconds=int(tablet.get("cache_seconds", 60)),
        wallpaper_enabled=bool(tablet.get("wallpaper_enabled", True)),
        wallpaper_provider=wallpaper_provider,
        wallpaper_url_template=str(
            tablet.get(
                "wallpaper_url_template",
                "https://picsum.photos/seed/homelab-{date}/{width}/{height}",
            )
        ),
        wallpaper_cache_dir=Path(tablet.get("wallpaper_cache_dir", "./data/wallpapers")),
        wallpaper_timeout_seconds=float(tablet.get("wallpaper_timeout_seconds", 15.0)),
        wallpaper_max_bytes=int(tablet.get("wallpaper_max_bytes", 26_214_400)),
        weather_icons_enabled=bool(tablet.get("weather_icons_enabled", True)),
        weather_icon_url_template=str(
            tablet.get(
                "weather_icon_url_template",
                "https://raw.githubusercontent.com/basmilius/meteocons/v2/"
                "production/fill/png/128/{icon}.png",
            )
        ),
        weather_icon_cache_dir=Path(tablet.get("weather_icon_cache_dir", "./data/weather-icons")),
        weather_icon_timeout_seconds=float(tablet.get("weather_icon_timeout_seconds", 5.0)),
    )

