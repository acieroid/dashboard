from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Callable

logger = logging.getLogger("homelab_status.weather")

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def describe_weather(code: int) -> str:
    if code == 0:
        return "Clear"
    if code in (1, 2):
        return "Partly cloudy"
    if code == 3:
        return "Overcast"
    if code in (45, 48):
        return "Fog"
    if code in (51, 53, 55, 56, 57):
        return "Drizzle"
    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        return "Rain"
    if code in (71, 73, 75, 77, 85, 86):
        return "Snow"
    if code in (95, 96, 99):
        return "Thunderstorm"
    return "Mixed"


def parse_forecast(payload: dict[str, Any], location_name: str) -> dict[str, Any]:
    current = payload["current"]
    daily = payload["daily"]
    result = {
        "location": location_name,
        "temperature_c": float(current["temperature_2m"]),
        "apparent_temperature_c": float(current["apparent_temperature"]),
        "condition": describe_weather(int(current["weather_code"])),
        "forecast_condition": describe_weather(int(daily["weather_code"][0])),
        "minimum_c": float(daily["temperature_2m_min"][0]),
        "maximum_c": float(daily["temperature_2m_max"][0]),
        "precipitation_probability": int(daily["precipitation_probability_max"][0]),
    }
    dates = daily.get("time", [])
    result["forecast"] = [
        {
            "date": str(date),
            "condition": describe_weather(int(daily["weather_code"][index])),
            "minimum_c": float(daily["temperature_2m_min"][index]),
            "maximum_c": float(daily["temperature_2m_max"][index]),
            "precipitation_probability": int(daily["precipitation_probability_max"][index]),
        }
        for index, date in enumerate(dates[:4])
    ]
    return result


class WeatherClient:
    def __init__(
        self,
        latitude: float,
        longitude: float,
        location_name: str,
        cache_seconds: int = 1_800,
        timeout_seconds: float = 5.0,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self.latitude = latitude
        self.longitude = longitude
        self.location_name = location_name
        self.cache_seconds = cache_seconds
        self.timeout_seconds = timeout_seconds
        self.opener = opener
        self._cached: dict[str, Any] | None = None
        self._cached_at = 0.0
        self._lock = threading.Lock()

    def get(self) -> dict[str, Any] | None:
        now = time.monotonic()
        if self._cached is not None and now - self._cached_at < self.cache_seconds:
            return self._cached
        with self._lock:
            now = time.monotonic()
            if self._cached is not None and now - self._cached_at < self.cache_seconds:
                return self._cached
            try:
                forecast = self._fetch()
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                logger.warning("weather_fetch_failed", exc_info=True)
                return self._cached
            self._cached = forecast
            self._cached_at = now
            return forecast

    def _fetch(self) -> dict[str, Any]:
        query = urllib.parse.urlencode(
            {
                "latitude": self.latitude,
                "longitude": self.longitude,
                "current": "temperature_2m,apparent_temperature,weather_code",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "Europe/Brussels",
                "forecast_days": 4,
            }
        )
        request = urllib.request.Request(
            f"{FORECAST_URL}?{query}",
            headers={"User-Agent": "homelab-status/0.1"},
        )
        with self.opener(request, timeout=self.timeout_seconds) as response:
            payload = json.load(response)
        return parse_forecast(payload, self.location_name)
