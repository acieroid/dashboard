from __future__ import annotations

import json
from datetime import date
from io import BytesIO
from pathlib import Path

from PIL import Image

from homelab_status.wallpaper import WallpaperCache, WikimediaPictureOfDayCache


def jpeg_bytes(color: tuple[int, int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGB", (64, 40), color).save(output, format="JPEG")
    return output.getvalue()


class Response(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def test_downloads_once_and_reuses_daily_wallpaper(tmp_path: Path) -> None:
    calls = []

    def opener(request, timeout):
        calls.append((request.full_url, timeout))
        return Response(jpeg_bytes((20, 80, 120)))

    cache = WallpaperCache(
        tmp_path,
        "https://example.test/{date}/{width}/{height}",
        1920,
        1200,
        opener=opener,
    )
    first = cache.get(date(2026, 10, 30))
    second = cache.get(date(2026, 10, 30))

    assert first is not None and first.size == (64, 40)
    assert second is not None
    assert calls == [("https://example.test/2026-10-30/1920/1200", 15.0)]


def test_uses_last_cached_wallpaper_after_failure(tmp_path: Path) -> None:
    old_path = tmp_path / "wallpaper-2026-10-29.image"
    old_path.write_bytes(jpeg_bytes((80, 40, 20)))

    def failing_opener(request, timeout):
        raise OSError("offline")

    cache = WallpaperCache(tmp_path, "https://example.test/{date}", 1920, 1200, opener=failing_opener)
    image = cache.get(date(2026, 10, 30))

    assert image is not None
    assert image.getpixel((0, 0))[0] > image.getpixel((0, 0))[2]


def test_resolves_wikimedia_picture_and_preserves_credit(tmp_path: Path) -> None:
    expanded = {"expandtemplates": {"wikitext": "Daily landscape.jpg"}}
    details = {
        "query": {
            "pages": [
                {
                    "imageinfo": [
                        {
                            "width": 2400,
                            "height": 1400,
                            "mime": "image/jpeg",
                            "thumburl": "https://upload.wikimedia.test/daily.jpg",
                            "url": "https://upload.wikimedia.test/original.jpg",
                            "extmetadata": {
                                "Artist": {"value": "<b>Jane Doe</b>"},
                                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                                "ImageDescription": {"value": "<i>Sunrise over a quiet valley</i>"},
                            },
                        }
                    ]
                }
            ]
        }
    }

    def opener(request, timeout):
        if "action=expandtemplates" in request.full_url:
            assert request.full_url.startswith("https://commons.wikimedia.org/w/api.php?")
            return Response(json.dumps(expanded).encode())
        if "prop=imageinfo" in request.full_url:
            return Response(json.dumps(details).encode())
        if "action=parse" in request.full_url:
            assert "text=%7B%7BPotd%2F2026-10-30+%28en%29%7D%7D" in request.full_url
            assert "page=" not in request.full_url
            return Response(
                json.dumps(
                    {
                        "parse": {
                            "text": (
                                '<style>.mw-parser-output{color:red}</style>'
                                '<p>Commons Main Page caption</p>'
                                '<span class="mw-editsection">[edit]</span>'
                            )
                        }
                    }
                ).encode()
            )
        assert request.full_url == "https://upload.wikimedia.test/daily.jpg"
        return Response(jpeg_bytes((30, 90, 120)))

    fallback = WallpaperCache(tmp_path, "https://fallback.test/{date}", 500, 500, opener=opener)
    cache = WikimediaPictureOfDayCache(tmp_path, 500, 500, fallback, opener=opener)
    asset = cache.get_asset(date(2026, 10, 30))

    assert asset.image is not None
    assert asset.description == "Commons Main Page caption"
