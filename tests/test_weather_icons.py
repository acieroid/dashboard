from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image

from homelab_status.weather_icons import MeteoconsCache, meteocons_slug


class Response(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def png_bytes(size: int) -> bytes:
    output = BytesIO()
    Image.new("RGBA", (size, size), (250, 190, 50, 255)).save(output, format="PNG")
    return output.getvalue()


def test_maps_conditions_to_meteocons_slugs() -> None:
    assert meteocons_slug("Clear") == "clear-day"
    assert meteocons_slug("Partly cloudy") == "partly-cloudy-day"
    assert meteocons_slug("Overcast") == "overcast"
    assert meteocons_slug("Fog") == "fog"
    assert meteocons_slug("Drizzle") == "drizzle"
    assert meteocons_slug("Rain") == "rain"
    assert meteocons_slug("Snow") == "snow"
    assert meteocons_slug("Thunderstorm") == "thunderstorms-day-rain"


def test_downloads_resizes_and_caches_icon(tmp_path: Path) -> None:
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)
        return Response(png_bytes(128))

    cache = MeteoconsCache(
        tmp_path,
        "https://icons.test/{icon}.png",
        opener=opener,
    )
    first = cache.get("Clear", 64)
    second = cache.get("Clear", 64)

    assert first is not None and first.size == (64, 64)
    assert second is not None and second.size == (64, 64)
    assert calls == ["https://icons.test/clear-day.png"]
