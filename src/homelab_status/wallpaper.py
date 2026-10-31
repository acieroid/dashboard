from __future__ import annotations

import html
import json
import logging
import os
import threading
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

from PIL import Image, UnidentifiedImageError

logger = logging.getLogger("homelab_status.wallpaper")

COMMONS_API = "https://commons.wikimedia.org/w/api.php"


@dataclass(frozen=True, slots=True)
class WallpaperAsset:
    image: Image.Image | None
    description: str | None = None


class WallpaperCache:
    """Download, validate, and retain one wallpaper per local calendar day."""

    def __init__(
        self,
        cache_dir: Path,
        url_template: str,
        width: int,
        height: int,
        timeout_seconds: float = 15.0,
        max_bytes: int = 26_214_400,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self.cache_dir = cache_dir
        self.url_template = url_template
        self.width = width
        self.height = height
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.opener = opener
        self._lock = threading.Lock()

    def get(self, day: date) -> Image.Image | None:
        target = self.cache_dir / f"wallpaper-{day.isoformat()}.image"
        if target.exists():
            try:
                return self._open(target)
            except (OSError, UnidentifiedImageError):
                logger.warning("wallpaper_cache_invalid", extra={"path": str(target)})
        with self._lock:
            if target.exists():
                try:
                    return self._open(target)
                except (OSError, UnidentifiedImageError):
                    try:
                        target.unlink()
                    except OSError:
                        return self._latest_cached(exclude=target)
            try:
                self._download(day, target)
                self._prune()
                return self._open(target)
            except (OSError, ValueError, UnidentifiedImageError):
                logger.warning("wallpaper_fetch_failed", exc_info=True)
                return self._latest_cached(exclude=target)

    def get_asset(self, day: date) -> WallpaperAsset:
        return WallpaperAsset(self.get(day))

    def _download(self, day: date, target: Path) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        url = self.url_template.format(date=day.isoformat(), width=self.width, height=self.height)
        request = urllib.request.Request(url, headers={"User-Agent": "homelab-status/0.1"})
        temporary = target.with_suffix(".tmp")
        total = 0
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response, temporary.open("wb") as output:
                while chunk := response.read(65_536):
                    total += len(chunk)
                    if total > self.max_bytes:
                        raise ValueError("wallpaper exceeds configured size limit")
                    output.write(chunk)
            with Image.open(temporary) as image:
                image.verify()
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def _open(path: Path) -> Image.Image:
        with Image.open(path) as image:
            return image.convert("RGB")

    def _latest_cached(self, exclude: Path | None = None) -> Image.Image | None:
        candidates = sorted(self.cache_dir.glob("wallpaper-*.image"), reverse=True)
        for candidate in candidates:
            if candidate == exclude:
                continue
            try:
                return self._open(candidate)
            except (OSError, UnidentifiedImageError):
                continue
        return None

    def _prune(self) -> None:
        for old_path in sorted(self.cache_dir.glob("wallpaper-*.image"), reverse=True)[7:]:
            try:
                old_path.unlink()
            except OSError:
                logger.warning("wallpaper_prune_failed", extra={"path": str(old_path)})


class _VisibleTextParser(HTMLParser):
    """Extract visible HTML text while discarding MediaWiki CSS and scripts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = next((value or "" for name, value in attrs if name == "class"), "")
        if self._hidden_depth or tag in {"style", "script", "noscript"} or "mw-editsection" in classes:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self.parts.append(data)


def _plain_text(value: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(value)
    return " ".join(html.unescape(" ".join(parser.parts)).split())


class WikimediaPictureOfDayCache:
    """Resolve the exact Commons Main Page Picture of the Day and cache it."""

    def __init__(
        self,
        cache_dir: Path,
        width: int,
        height: int,
        fallback: WallpaperCache,
        timeout_seconds: float = 15.0,
        max_bytes: int = 26_214_400,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self.cache_dir = cache_dir
        self.width = width
        self.height = height
        self.fallback = fallback
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.opener = opener
        self._lock = threading.Lock()

    def get_asset(self, day: date) -> WallpaperAsset:
        # v2 invalidates captions cached by the former full-template-page parser.
        image_path = self.cache_dir / f"commons-potd-v2-{day.isoformat()}.image"
        metadata_path = self.cache_dir / f"commons-potd-v2-{day.isoformat()}.json"
        cached = self._open_asset(image_path, metadata_path)
        if cached:
            return cached
        with self._lock:
            cached = self._open_asset(image_path, metadata_path)
            if cached:
                return cached
            try:
                source = self._find_source(day)
                self._download(source["url"], image_path)
                self._write_metadata(metadata_path, source)
                self._prune()
                return WallpaperAsset(self._open(image_path), source["description"])
            except (OSError, ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError, UnidentifiedImageError):
                logger.warning("wikimedia_wallpaper_fetch_failed", exc_info=True)
                previous = self._latest_cached()
                return previous or self.fallback.get_asset(day)

    def _find_source(self, requested_day: date) -> dict[str, str]:
        date_text = requested_day.isoformat()
        expanded = self._json_request(
            {
                "action": "expandtemplates",
                "format": "json",
                "formatversion": "2",
                "prop": "wikitext",
                "text": "{{Potd/" + date_text + "}}",
            }
        )
        filename = _plain_text(str(expanded["expandtemplates"]["wikitext"])).strip()
        if not filename.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            raise ValueError("Commons Picture of the Day is not a supported raster image")
        if not filename.startswith("File:"):
            filename = f"File:{filename}"

        details = self._json_request(
            {
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "prop": "imageinfo",
                "iiprop": "url|size|mime|extmetadata",
                "iiurlwidth": str(max(1_000, self.width * 2)),
                "titles": filename,
            }
        )
        info = details["query"]["pages"][0]["imageinfo"][0]
        mime = str(info.get("mime", ""))
        if mime not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValueError("Commons Picture of the Day has an unsupported media type")

        caption_response = self._json_request(
            {
                "action": "parse",
                "format": "json",
                "formatversion": "2",
                "prop": "text",
                # Parse the transclusion, not the template page itself. The latter
                # includes documentation, language links, and embedded CSS.
                "text": "{{Potd/" + date_text + " (en)}}",
                "contentmodel": "wikitext",
                "disableeditsection": "1",
            }
        )
        caption = _plain_text(str(caption_response["parse"]["text"]))
        metadata = info.get("extmetadata", {})
        description = caption or _plain_text(str(metadata.get("ImageDescription", {}).get("value", "")))
        if not description:
            description = filename.removeprefix("File:").rsplit(".", 1)[0].replace("_", " ")
        return {
            "url": str(info.get("thumburl") or info["url"]),
            "source_date": date_text,
            "filename": filename,
            "description": description,
        }

    def _json_request(self, parameters: dict[str, str]) -> dict[str, Any]:
        url = f"{COMMONS_API}?{urllib.parse.urlencode(parameters)}"
        request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "homelab-status/0.1"})
        with self.opener(request, timeout=self.timeout_seconds) as response:
            return json.load(response)

    def _download(self, url: str, target: Path) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        request = urllib.request.Request(url, headers={"User-Agent": "homelab-status/0.1"})
        total = 0
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response, temporary.open("wb") as output:
                while chunk := response.read(65_536):
                    total += len(chunk)
                    if total > self.max_bytes:
                        raise ValueError("wallpaper exceeds configured size limit")
                    output.write(chunk)
            with Image.open(temporary) as image:
                image.verify()
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def _open(path: Path) -> Image.Image:
        with Image.open(path) as image:
            return image.convert("RGB")

    def _open_asset(self, image_path: Path, metadata_path: Path) -> WallpaperAsset | None:
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            return WallpaperAsset(
                self._open(image_path),
                str(metadata.get("description") or "") or None,
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError, UnidentifiedImageError):
            return None

    @staticmethod
    def _write_metadata(path: Path, source: dict[str, str]) -> None:
        temporary = path.with_suffix(".tmp")
        try:
            temporary.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _latest_cached(self) -> WallpaperAsset | None:
        for image_path in sorted(self.cache_dir.glob("commons-potd-v2-*.image"), reverse=True):
            asset = self._open_asset(image_path, image_path.with_suffix(".json"))
            if asset:
                return asset
        return None

    def _prune(self) -> None:
        images = sorted(self.cache_dir.glob("commons-potd-v2-*.image"), reverse=True)
        for image_path in images[7:]:
            for path in (image_path, image_path.with_suffix(".json")):
                try:
                    path.unlink()
                except OSError:
                    logger.warning("wikimedia_wallpaper_prune_failed", extra={"path": str(path)})
