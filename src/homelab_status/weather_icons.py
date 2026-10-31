from __future__ import annotations

import logging
import os
import threading
import urllib.request
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

from PIL import Image, UnidentifiedImageError

logger = logging.getLogger("homelab_status.weather_icons")


def meteocons_slug(condition: str) -> str:
    lower = condition.lower()
    if "thunder" in lower or "storm" in lower:
        return "thunderstorms-day-rain"
    if "snow" in lower:
        return "snow"
    if "drizzle" in lower:
        return "drizzle"
    if "rain" in lower or "shower" in lower:
        return "rain"
    if "fog" in lower or "mist" in lower:
        return "fog"
    if "overcast" in lower:
        return "overcast"
    if "partly" in lower or "cloud" in lower:
        return "partly-cloudy-day"
    if "clear" in lower or "sun" in lower:
        return "clear-day"
    return "partly-cloudy-day"


class MeteoconsCache:
    def __init__(
        self,
        cache_dir: Path,
        url_template: str,
        timeout_seconds: float = 5.0,
        max_bytes: int = 262_144,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self.cache_dir = cache_dir
        self.url_template = url_template
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.opener = opener
        self._lock = threading.Lock()

    def get(self, condition: str, size: int = 128) -> Image.Image | None:
        slug = meteocons_slug(condition)
        target = self.cache_dir / f"{slug}-{size}.png"
        if target.exists():
            return self._open(target)
        with self._lock:
            if target.exists():
                return self._open(target)
            try:
                source = self._download(slug)
                with Image.open(BytesIO(source)) as image:
                    image.load()
                    rendered = image.convert("RGBA")
                    if rendered.size != (size, size):
                        rendered = rendered.resize((size, size), Image.Resampling.LANCZOS)
                output = BytesIO()
                rendered.save(output, format="PNG")
                png = output.getvalue()
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix(".tmp")
                try:
                    temporary.write_bytes(png)
                    with Image.open(temporary) as image:
                        image.verify()
                    os.replace(temporary, target)
                finally:
                    if temporary.exists():
                        temporary.unlink()
                return self._open(target)
            except (OSError, ValueError, UnidentifiedImageError):
                logger.warning("meteocons_fetch_failed", extra={"icon": slug}, exc_info=True)
                return None

    def _download(self, slug: str) -> bytes:
        url = self.url_template.format(icon=slug)
        request = urllib.request.Request(
            url,
            headers={"Accept": "image/png", "User-Agent": "homelab-status/0.1"},
        )
        content = bytearray()
        with self.opener(request, timeout=self.timeout_seconds) as response:
            while chunk := response.read(16_384):
                content.extend(chunk)
                if len(content) > self.max_bytes:
                    raise ValueError("weather icon exceeds configured size limit")
        if not bytes(content).startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("weather icon response is not PNG")
        return bytes(content)

    @staticmethod
    def _open(path: Path) -> Image.Image:
        with Image.open(path) as image:
            return image.convert("RGBA")
