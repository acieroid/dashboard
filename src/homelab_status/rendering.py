from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

WIDTH = 400
HEIGHT = 300
MARGIN = 10
INK = 0
PAPER = 1

SERIF_BOLD = (
    Path("/usr/share/fonts/truetype/librebaskerville/LibreBaskerville-Bold.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"),
)
SERIF_ITALIC = (
    Path("/usr/share/fonts/truetype/librebaskerville/LibreBaskerville-Italic.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf"),
)
SANS_REGULAR = (
    Path("/usr/share/fonts/truetype/ibm-plex/IBMPlexSans-Regular.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
)
SANS_BOLD = (
    Path("/usr/share/fonts/truetype/ibm-plex/IBMPlexSans-SemiBold.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
)
MONO_REGULAR = (
    Path("/usr/share/fonts/truetype/ibm-plex/IBMPlexMono-Regular.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
)


def _font(paths: Iterable[Path], size: int) -> ImageFont.ImageFont:
    for path in paths:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    left, _, right, _ = draw.textbbox((0, 0), text, font=font)
    return right - left


def _fit_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    """Ellipsize text using measured glyph widths, never character estimates."""
    if max_width <= 0:
        return ""
    if _text_width(draw, text, font) <= max_width:
        return text
    ellipsis = "…"
    if _text_width(draw, ellipsis, font) > max_width:
        return ""
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if _text_width(draw, text[:middle].rstrip() + ellipsis, font) <= max_width:
            low = middle
        else:
            high = middle - 1
    return text[:low].rstrip() + ellipsis


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    max_lines: int = 2,
) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    while words:
        word = words.pop(0)
        candidate = f"{current} {word}".strip()
        if not current or _text_width(draw, candidate, font) <= max_width:
            current = candidate
            continue
        lines.append(current)
        current = word
        if len(lines) == max_lines - 1:
            lines.append(_fit_text(draw, " ".join([current, *words]), font, max_width))
            return lines
    if current:
        lines.append(_fit_text(draw, current, font, max_width))
    return lines[:max_lines]


def _bytes(value: int | None) -> str:
    if value is None:
        return ""
    amount = float(value)
    for suffix in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(amount) < 1024 or suffix == "TiB":
            if suffix in ("B", "KiB", "MiB"):
                return f"{amount:.0f} {suffix}"
            return f"{amount:.1f} {suffix}"
        amount /= 1024
    return ""


def _duration(seconds: int) -> str:
    days, remainder = divmod(seconds, 86_400)
    hours = remainder // 3_600
    if days:
        return f"{days}d {hours}h"
    minutes = (remainder % 3_600) // 60
    return f"{hours}h {minutes}m" if hours else f"{minutes}m"


def _load_average(value: float) -> str:
    rendered = f"{value:.2f}"
    return rendered[1:] if rendered.startswith("0.") else rendered


def _backup_age(timestamp: str, now: datetime) -> str:
    snapshot = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    seconds = max(0, int((now.astimezone(snapshot.tzinfo) - snapshot).total_seconds()))
    if seconds < 3_600:
        return f"{seconds // 60}m ago"
    if seconds < 86_400:
        return f"{seconds // 3_600}h ago"
    return f"{seconds // 86_400}d ago"


def _short_age(seconds: int | None) -> str:
    if seconds is None:
        return ""
    if seconds < 60:
        return "now"
    if seconds < 3_600:
        return f"{seconds // 60}m"
    if seconds < 86_400:
        return f"{seconds // 3_600}h"
    return f"{seconds // 86_400}d"


def _backup_health(backup: dict[str, Any], now: datetime, stale_after_hours: int) -> str:
    if backup.get("last_run_successful") is False:
        return "FAILED"
    snapshot = datetime.fromisoformat(str(backup["snapshot_time"]).replace("Z", "+00:00"))
    age_seconds = max(0, (now.astimezone(snapshot.tzinfo) - snapshot).total_seconds())
    return "LATE" if age_seconds > stale_after_hours * 3_600 else "OK"


def _report_age_label(peer: dict[str, Any]) -> str:
    age = _short_age(peer.get("age_seconds"))
    state = str(peer.get("state", "missing"))
    if state == "fresh":
        return "now" if age == "now" else f"{age} ago"
    if state == "stale":
        return f"{age} late" if age else "late"
    return "offline"


def _draw_warning(draw: ImageDraw.ImageDraw, x: int, y: int, font: ImageFont.ImageFont) -> None:
    draw.polygon(((x + 5, y), (x, y + 10), (x + 10, y + 10)), outline=INK, fill=PAPER)
    draw.text((x + 5, y + 1), "!", font=font, fill=INK, anchor="ma")


def _draw_weather_icon(draw: ImageDraw.ImageDraw, x: int, y: int, condition: str) -> None:
    """Draw a restrained 20×20 icon using only one-bit primitives."""
    lower = condition.lower()
    if "clear" in lower or "sun" in lower:
        draw.ellipse((x + 6, y + 5, x + 14, y + 13), outline=INK)
        for start, end in (
            ((x + 10, y + 1), (x + 10, y + 3)),
            ((x + 10, y + 15), (x + 10, y + 18)),
            ((x + 2, y + 9), (x + 4, y + 9)),
            ((x + 16, y + 9), (x + 19, y + 9)),
            ((x + 4, y + 3), (x + 5, y + 5)),
            ((x + 15, y + 14), (x + 17, y + 16)),
        ):
            draw.line((*start, *end), fill=INK)
        return

    draw.arc((x + 2, y + 6, x + 12, y + 15), 170, 350, fill=INK)
    draw.arc((x + 7, y + 3, x + 17, y + 14), 185, 340, fill=INK)
    draw.line((x + 4, y + 13, x + 17, y + 13), fill=INK)
    if "rain" in lower or "drizzle" in lower or "storm" in lower:
        draw.line((x + 6, y + 15, x + 4, y + 18), fill=INK)
        draw.line((x + 12, y + 15, x + 10, y + 18), fill=INK)
        draw.line((x + 17, y + 15, x + 15, y + 18), fill=INK)
    elif "snow" in lower:
        draw.point((x + 5, y + 17), fill=INK)
        draw.point((x + 11, y + 17), fill=INK)
        draw.point((x + 17, y + 17), fill=INK)


def _draw_header(
    draw: ImageDraw.ImageDraw,
    generated: datetime,
    weather: dict[str, Any] | None,
    fonts: dict[str, ImageFont.ImageFont],
) -> None:
    draw.text((MARGIN, 4), generated.strftime("%a %d %b %Y"), font=fonts["date"], fill=INK)
    iso = generated.isocalendar()
    draw.text(
        (MARGIN + 1, 34),
        f"week {iso.week} · day {generated.timetuple().tm_yday} · {generated:%H:%M}",
        font=fonts["label"],
        fill=INK,
    )

    weather_x = 228
    if weather:
        condition = str(weather["condition"])
        _draw_weather_icon(draw, weather_x, 7, condition)
        draw.text((weather_x + 27, 3), str(weather["location"]), font=fonts["weather_bold"], fill=INK)
        current = f"{weather['temperature_c']:.0f}°  {condition}"
        draw.text(
            (weather_x + 27, 19),
            _fit_text(draw, current, fonts["weather"], WIDTH - MARGIN - weather_x - 27),
            font=fonts["weather"],
            fill=INK,
        )
        forecast = f"today {weather['minimum_c']:.0f}–{weather['maximum_c']:.0f}° · rain {weather['precipitation_probability']}%"
        draw.text(
            (weather_x + 27, 36),
            _fit_text(draw, forecast, fonts["label"], WIDTH - MARGIN - weather_x - 27),
            font=fonts["label"],
            fill=INK,
        )
    else:
        draw.text((weather_x, 18), "Brussels · weather unavailable", font=fonts["label"], fill=INK)
    draw.line((MARGIN, 57, WIDTH - MARGIN, 57), fill=INK)


def _disk_text(disks: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for disk in disks[:2]:
        total = int(disk["total_bytes"])
        percent = round(int(disk["used_bytes"]) * 100 / total) if total else 0
        parts.append(f"disk {disk['mount_point']} {percent}% · {_bytes(int(disk['available_bytes']))} free")
    return " · ".join(parts)


def _backup_text(backups: list[dict[str, Any]], now: datetime, stale_after_hours: int) -> str:
    if not backups:
        return ""
    latest = max(backups, key=lambda item: item["snapshot_time"])
    result = f"backup {_backup_health(latest, now, stale_after_hours)} · {_backup_age(latest['snapshot_time'], now)}"
    changed = _bytes(latest.get("data_added_bytes"))
    return f"{result} · +{changed}" if changed else result


def _system_text(report: dict[str, Any]) -> str:
    parts: list[str] = []
    load_average = report.get("load_average")
    if load_average:
        parts.append("load " + " ".join(_load_average(float(value)) for value in load_average))
    memory_available = report.get("memory_available_bytes")
    if memory_available is not None:
        memory_total = report.get("memory_total_bytes")
        if memory_total is not None:
            parts.append(f"mem {_bytes(int(memory_available))}/{_bytes(int(memory_total))} avail")
        else:
            parts.append(f"mem {_bytes(int(memory_available))} avail")
    return " · ".join(parts)


def _draw_machine(
    draw: ImageDraw.ImageDraw,
    peer: dict[str, Any],
    y: int,
    generated: datetime,
    backup_stale_after_hours: int,
    fonts: dict[str, ImageFont.ImageFont],
) -> None:
    name_x = MARGIN + 13
    right_x = WIDTH - MARGIN
    state = str(peer.get("state", "missing"))
    dot_bounds = (MARGIN, y + 9, MARGIN + 7, y + 16)
    if state == "fresh":
        draw.ellipse(dot_bounds, fill=INK)
    else:
        draw.ellipse(dot_bounds, outline=INK)
    report = peer.get("report")
    reboot_required = bool(report and report.get("reboot_required") is True)
    age_label = _report_age_label(peer)
    age_width = _text_width(draw, age_label, fonts["label"])
    name_width = right_x - age_width - 20 - name_x - (17 if reboot_required else 0)
    name = _fit_text(draw, str(peer["name"]).upper(), fonts["name"], name_width)
    draw.text((name_x, y + 2), name, font=fonts["name"], fill=INK)
    if reboot_required:
        warning_x = name_x + _text_width(draw, name, fonts["name"]) + 6
        _draw_warning(draw, warning_x, y + 5, fonts["warning"])
    draw.text((right_x, y + 5), age_label, font=fonts["label"], fill=INK, anchor="ra")

    if not report:
        draw.text((name_x, y + 27), "Awaiting status report", font=fonts["primary"], fill=INK)
        return

    primary_parts = [f"uptime {_duration(int(report['uptime_seconds']))}"]
    disk_text = _disk_text(list(report.get("disks", [])))
    if disk_text:
        primary_parts.append(disk_text)
    primary_text = " · ".join(primary_parts)
    draw.text(
        (name_x, y + 25),
        _fit_text(draw, primary_text, fonts["primary"], right_x - name_x),
        font=fonts["primary"],
        fill=INK,
    )

    secondary_parts: list[str] = []
    backup_text = _backup_text(list(report.get("restic_backups", [])), generated, backup_stale_after_hours)
    if backup_text:
        secondary_parts.append(backup_text)
    system_text = _system_text(report)
    if system_text:
        secondary_parts.append(system_text)
    if secondary_parts:
        secondary_text = " · ".join(secondary_parts)
        draw.text(
            (name_x, y + 43),
            _fit_text(draw, secondary_text, fonts["secondary"], right_x - name_x),
            font=fonts["secondary"],
            fill=INK,
        )


def render_dashboard(
    snapshot: dict[str, Any],
    *,
    timezone: str = "Europe/Brussels",
    quote: str = "Small steps, repeated, become reliable systems.",
    backup_stale_after_hours: int = 36,
) -> Image.Image:
    generated = datetime.fromisoformat(str(snapshot["generated_at"])).astimezone(ZoneInfo(timezone))
    image = Image.new("1", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(image)
    fonts = {
        "date": _font(SERIF_BOLD, 22),
        "quote": _font(SERIF_ITALIC, 12),
        "name": _font(SANS_BOLD, 17),
        "weather_bold": _font(SANS_BOLD, 13),
        "weather": _font(SANS_REGULAR, 13),
        "label": _font(SANS_REGULAR, 11),
        "primary": _font(MONO_REGULAR, 12),
        "secondary": _font(SANS_REGULAR, 11),
        "warning": _font(SANS_BOLD, 9),
    }

    _draw_header(draw, generated, snapshot.get("weather"), fonts)
    row_top = 62
    row_height = 62
    for index, peer in enumerate(list(snapshot.get("peers", []))[:3]):
        y = row_top + index * row_height
        _draw_machine(draw, peer, y, generated, backup_stale_after_hours, fonts)
        if index < 2:
            draw.line((MARGIN, y + row_height - 1, WIDTH - MARGIN, y + row_height - 1), fill=INK)

    draw.line((MARGIN, 252, WIDTH - MARGIN, 252), fill=INK)
    quote_lines = _wrap_text(draw, quote, fonts["quote"], WIDTH - 2 * MARGIN - 12, max_lines=2)
    start_y = 273 if len(quote_lines) == 1 else 264
    for index, quote_line in enumerate(quote_lines):
        draw.text(
            (WIDTH // 2, start_y + index * 18),
            quote_line,
            font=fonts["quote"],
            fill=INK,
            anchor="mm",
        )
    return image


def render_png(
    snapshot: dict[str, Any],
    *,
    timezone: str,
    quote: str,
    backup_stale_after_hours: int = 36,
) -> bytes:
    output = BytesIO()
    render_dashboard(
        snapshot,
        timezone=timezone,
        quote=quote,
        backup_stale_after_hours=backup_stale_after_hours,
    ).save(output, format="PNG", optimize=True)
    return output.getvalue()


def render_framebuffer(
    snapshot: dict[str, Any],
    *,
    timezone: str,
    quote: str,
    backup_stale_after_hours: int = 36,
) -> bytes:
    """Pack the 1-bit dashboard row-wise, MSB first, with 1 meaning white."""
    image = render_dashboard(
        snapshot,
        timezone=timezone,
        quote=quote,
        backup_stale_after_hours=backup_stale_after_hours,
    )
    output = bytearray()
    pixels = image.load()
    for y in range(HEIGHT):
        for byte_x in range(0, WIDTH, 8):
            value = 0
            for bit in range(8):
                if pixels[byte_x + bit, y]:
                    value |= 1 << (7 - bit)
            output.append(value)
    return bytes(output)
