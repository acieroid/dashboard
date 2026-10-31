from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .rendering import _backup_age, _backup_health, _bytes, _duration, _load_average, _short_age

SERIF_REGULAR = (
    Path("/usr/share/fonts/truetype/librebaskerville/LibreBaskerville-Regular.ttf"),
    Path("/usr/share/fonts/truetype/baskerville/GFSBaskerville.otf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
)
SERIF_DISPLAY_BOLD = (
    Path("/usr/share/fonts/truetype/librebaskerville/LibreBaskerville-Bold.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"),
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

WHITE = (248, 248, 244, 255)
MUTED = (222, 226, 226, 255)
GREEN = (102, 220, 155, 255)
AMBER = (245, 190, 78, 255)
RED = (246, 105, 105, 255)


def _font(paths: Iterable[Path], size: int) -> ImageFont.ImageFont:
    for path in paths:
        if path.exists():
            return ImageFont.truetype(str(path), max(8, size))
    return ImageFont.load_default()


def _fit_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
        return text
    ellipsis = "…"
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if draw.textbbox((0, 0), text[:middle].rstrip() + ellipsis, font=font)[2] <= max_width:
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
        if not current or draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
            continue
        lines.append(current)
        current = word
        if len(lines) == max_lines - 1:
            remainder = " ".join([current, *words])
            lines.append(_fit_text(draw, remainder, font, max_width))
            return lines
    if current:
        lines.append(_fit_text(draw, current, font, max_width))
    return lines[:max_lines]


def _cover(background: Image.Image | None, size: tuple[int, int]) -> Image.Image:
    if background is None:
        width, height = size
        image = Image.new("RGB", size)
        draw = ImageDraw.Draw(image)
        for y in range(height):
            ratio = y / max(1, height - 1)
            color = (36 + int(30 * ratio), 54 + int(25 * ratio), 68 + int(24 * ratio))
            draw.line((0, y, width, y), fill=color)
        return image
    return ImageOps.fit(background.convert("RGB"), size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))


def _apply_readability_overlay(image: Image.Image) -> Image.Image:
    width, height = image.size
    base = image.convert("RGBA")
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 24))
    gradient = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(gradient)
    for y in range(height):
        position = y / max(1, height - 1)
        top_alpha = max(0, int(90 * (1 - position / 0.42))) if position < 0.42 else 0
        bottom_alpha = int(115 * max(0, (position - 0.42) / 0.58))
        draw.line((0, y, width, y), fill=(0, 0, 0, max(top_alpha, bottom_alpha)))
    return Image.alpha_composite(Image.alpha_composite(base, overlay), gradient)


def _draw_shadowed_text(
    draw: ImageDraw.ImageDraw,
    position: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int] = WHITE,
    anchor: str | None = None,
    shadow: int = 2,
) -> None:
    x, y = position
    draw.text((x + shadow, y + shadow), text, font=font, fill=(0, 0, 0, 145), anchor=anchor)
    draw.text((x, y), text, font=font, fill=fill, anchor=anchor)


def _draw_weather_icon(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    size: int,
    condition: str,
    color: tuple[int, int, int, int] = WHITE,
) -> None:
    scale = size / 48
    line = max(2, round(2.5 * scale))
    lower = condition.lower()
    if "clear" in lower or "sun" in lower:
        draw.ellipse((x + 14 * scale, y + 14 * scale, x + 34 * scale, y + 34 * scale), outline=color, width=line)
        for x1, y1, x2, y2 in ((24, 3, 24, 10), (24, 38, 24, 45), (3, 24, 10, 24), (38, 24, 45, 24)):
            draw.line((x + x1 * scale, y + y1 * scale, x + x2 * scale, y + y2 * scale), fill=color, width=line)
        return
    draw.arc((x + 4 * scale, y + 18 * scale, x + 29 * scale, y + 40 * scale), 165, 350, fill=color, width=line)
    draw.arc((x + 17 * scale, y + 9 * scale, x + 43 * scale, y + 37 * scale), 180, 345, fill=color, width=line)
    draw.line((x + 10 * scale, y + 34 * scale, x + 42 * scale, y + 34 * scale), fill=color, width=line)
    if "rain" in lower or "drizzle" in lower or "storm" in lower:
        for offset in (14, 25, 36):
            draw.line((x + offset * scale, y + 39 * scale, x + (offset - 4) * scale, y + 46 * scale), fill=color, width=line)
    elif "snow" in lower:
        for offset in (14, 25, 36):
            draw.ellipse((x + offset * scale, y + 41 * scale, x + (offset + 2) * scale, y + 43 * scale), fill=color)


def _paste_weather_icon(canvas: Image.Image, icon: Image.Image, x: int, y: int, size: int) -> None:
    rendered = ImageOps.contain(icon.convert("RGBA"), (size, size), method=Image.Resampling.LANCZOS)
    canvas.alpha_composite(rendered, (x + (size - rendered.width) // 2, y + (size - rendered.height) // 2))


def _status(peer: dict[str, Any]) -> tuple[str, tuple[int, int, int, int]]:
    state = str(peer.get("state", "missing"))
    if state == "fresh":
        return "ONLINE", GREEN
    if state == "stale":
        return "STALE", AMBER
    return "OFFLINE", RED


def _update_age(peer: dict[str, Any]) -> str:
    age = _short_age(peer.get("age_seconds"))
    state = str(peer.get("state", "missing"))
    if not age:
        return "no report"
    if state == "fresh":
        return "updated now" if age == "now" else f"updated {age} ago"
    if state == "stale":
        return f"updated {age} ago"
    return f"last update {age} ago"


def _compact_metric_parts(report: dict[str, Any], now: datetime, backup_stale_after_hours: int) -> list[str]:
    parts = [f"Uptime {_duration(int(report['uptime_seconds']))}"]
    for disk in list(report.get("disks", []))[:2]:
        total = int(disk["total_bytes"])
        used_percent = round(int(disk["used_bytes"]) * 100 / total) if total else 0
        parts.append(f"{disk['mount_point']} {used_percent}% · {_bytes(int(disk['available_bytes']))} free")
    backups = list(report.get("restic_backups", []))
    if backups:
        latest = max(backups, key=lambda item: item["snapshot_time"])
        backup = f"Backup {_backup_health(latest, now, backup_stale_after_hours)} · {_backup_age(latest['snapshot_time'], now)}"
        changed = _bytes(latest.get("data_added_bytes"))
        parts.append(f"{backup} · +{changed}" if changed else backup)
    load = report.get("load_average")
    if load:
        parts.append("Load " + " ".join(_load_average(float(value)) for value in load))
    memory = report.get("memory_available_bytes")
    if memory is not None:
        total_memory = report.get("memory_total_bytes")
        if total_memory is not None:
            parts.append(f"Mem {_bytes(int(memory))} / {_bytes(int(total_memory))} available")
        else:
            parts.append(f"Mem {_bytes(int(memory))} available")
    return parts


def _system_identity(report: dict[str, Any]) -> str:
    os_version = report.get("os_version")
    kernel = report.get("kernel_version")
    if os_version and kernel:
        return f"{os_version} · Linux {kernel}"
    return str(os_version or (f"Linux {kernel}" if kernel else ""))


def _compact_metric_lines(
    draw: ImageDraw.ImageDraw,
    parts: list[str],
    font: ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    lines: list[str] = []
    current = ""
    for part in parts:
        candidate = f"{current}  ·  {part}" if current else part
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = part
    if current:
        lines.append(current)
    if len(lines) > 3:
        overflow = "  ·  ".join(lines[2:])
        lines = [lines[0], lines[1], _fit_text(draw, overflow, font, max_width)]
    return lines


def _draw_compact_panel(
    canvas: Image.Image,
    peer: dict[str, Any],
    box: tuple[int, int, int, int],
    scale: float,
    generated: datetime,
    backup_stale_after_hours: int,
) -> None:
    x1, y1, x2, _ = box
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rounded_rectangle(
        box,
        radius=max(8, round(13 * scale)),
        fill=(7, 13, 18, 158),
        outline=(255, 255, 255, 30),
        width=1,
    )
    canvas.alpha_composite(overlay)
    draw = ImageDraw.Draw(canvas)
    padding = round(13 * scale)
    left = x1 + padding
    right = x2 - padding
    name_font = _font(SANS_BOLD, round(18 * scale))
    identity_font = _font(SANS_REGULAR, round(9 * scale))
    status_font = _font(SANS_BOLD, round(10 * scale))
    update_font = _font(SANS_REGULAR, round(10 * scale))
    metric_font = _font(SANS_REGULAR, round(13 * scale))
    status_label, status_color = _status(peer)

    report = peer.get("report")
    identity = _system_identity(report) if report else ""
    vertical_shift = round(7 * scale) if identity else 0
    if identity:
        identity = _fit_text(draw, identity, identity_font, right - left)
        draw.text((left, y1 + round(2 * scale)), identity, font=identity_font, fill=MUTED)

    dot = max(3, round(4 * scale))
    draw.ellipse((left, y1 + round(15 * scale) + vertical_shift, left + dot * 2, y1 + round(15 * scale) + vertical_shift + dot * 2), fill=status_color)
    name_x = left + dot * 2 + round(7 * scale)
    update = _update_age(peer)
    update_width = draw.textbbox((0, 0), update, font=update_font)[2]
    name = _fit_text(draw, str(peer["name"]).upper(), name_font, right - update_width - name_x - round(12 * scale))
    draw.text((name_x, y1 + round(7 * scale) + vertical_shift), name, font=name_font, fill=WHITE)
    draw.text((right, y1 + round(10 * scale) + vertical_shift), update, font=update_font, fill=MUTED, anchor="ra")
    draw.text((name_x, y1 + round(28 * scale) + vertical_shift), status_label, font=status_font, fill=status_color)

    if report and report.get("reboot_required") is True:
        draw.text((right, y1 + round(28 * scale) + vertical_shift), "REBOOT REQUIRED", font=status_font, fill=AMBER, anchor="ra")
    if not report:
        draw.text((name_x, y1 + round(49 * scale) + vertical_shift), "No status data available", font=metric_font, fill=MUTED)
        return

    lines = _compact_metric_lines(
        draw,
        _compact_metric_parts(report, generated, backup_stale_after_hours),
        metric_font,
        right - name_x,
    )
    for index, line in enumerate(lines):
        draw.text((name_x, y1 + round((48 + index * 18) * scale) + vertical_shift), line, font=metric_font, fill=WHITE)


def _render_compact_widget(
    canvas: Image.Image,
    snapshot: dict[str, Any],
    generated: datetime,
    width: int,
    height: int,
    backup_stale_after_hours: int,
    quote: str | None,
    background_description: str | None,
    weather_icon: Image.Image | None,
) -> Image.Image:
    scale = min(width / 500, height / 500)
    draw = ImageDraw.Draw(canvas)
    margin = round(14 * scale)
    time_font = _font(SERIF_DISPLAY_BOLD, round(60 * scale))
    date_font = _font(SERIF_ITALIC, round(19 * scale))
    _draw_shadowed_text(draw, (margin, round(12 * scale)), generated.strftime("%H:%M"), time_font, shadow=max(1, round(2 * scale)))
    _draw_shadowed_text(draw, (margin + round(2 * scale), round(72 * scale)), generated.strftime("%a, %d %b %Y"), date_font, shadow=1)

    weather = snapshot.get("weather")
    if weather:
        weather_x = round(width * 0.58)
        city_font = _font(SANS_BOLD, round(12 * scale))
        temp_font = _font(SERIF_REGULAR, round(30 * scale))
        detail_font = _font(SANS_REGULAR, round(11 * scale))
        icon_size = round(38 * scale)
        if weather_icon:
            _paste_weather_icon(canvas, weather_icon, weather_x, round(18 * scale), icon_size)
            draw = ImageDraw.Draw(canvas)
        else:
            _draw_weather_icon(draw, weather_x, round(22 * scale), icon_size, str(weather["condition"]))
        text_x = weather_x + icon_size + round(7 * scale)
        _draw_shadowed_text(draw, (text_x, round(12 * scale)), str(weather["location"]), city_font, shadow=1)
        _draw_shadowed_text(draw, (text_x, round(27 * scale)), f"{weather['temperature_c']:.0f}°", temp_font, shadow=1)
        detail = f"{weather['condition']} · {weather['minimum_c']:.0f}–{weather['maximum_c']:.0f}° · {weather['precipitation_probability']}%"
        detail = _fit_text(draw, detail, detail_font, width - margin - weather_x)
        _draw_shadowed_text(draw, (weather_x, round(65 * scale)), detail, detail_font, shadow=1)

    if quote:
        quote_font = _font(SERIF_ITALIC, round(14 * scale))
        quote_lines = _wrap_text(draw, quote, quote_font, width - margin * 2, max_lines=2)
        for index, quote_line in enumerate(quote_lines):
            _draw_shadowed_text(
                draw,
                (width // 2, round((94 + index * 17) * scale)),
                quote_line,
                quote_font,
                anchor="ma",
                shadow=1,
            )
    if background_description:
        description_font = _font(SANS_REGULAR, round(11 * scale))
        description = _fit_text(draw, background_description, description_font, width - margin * 2)
        _draw_shadowed_text(
            draw,
            (width // 2, round(132 * scale)),
            description,
            description_font,
            anchor="ma",
            shadow=1,
        )
    panel_top = round(158 * scale)
    panel_gap = round(7 * scale)
    panel_height = (height - panel_top - margin - panel_gap * 2) // 3
    for index, peer in enumerate(list(snapshot.get("peers", []))[:3]):
        top = panel_top + index * (panel_height + panel_gap)
        _draw_compact_panel(
            canvas,
            peer,
            (margin, top, width - margin, top + panel_height),
            scale,
            generated,
            backup_stale_after_hours,
        )
    return canvas.convert("RGB")


def render_tablet_dashboard(
    snapshot: dict[str, Any],
    background: Image.Image | None,
    *,
    width: int = 500,
    height: int = 500,
    timezone: str = "Europe/Brussels",
    backup_stale_after_hours: int = 36,
    quote: str | None = None,
    background_description: str | None = None,
    weather_icon: Image.Image | None = None,
) -> Image.Image:
    generated = datetime.fromisoformat(str(snapshot["generated_at"])).astimezone(ZoneInfo(timezone))
    canvas = _apply_readability_overlay(_cover(background, (width, height)))
    return _render_compact_widget(
        canvas,
        snapshot,
        generated,
        width,
        height,
        backup_stale_after_hours,
        quote,
        background_description,
        weather_icon,
    )


def render_tablet_png(
    snapshot: dict[str, Any],
    background: Image.Image | None,
    *,
    width: int,
    height: int,
    timezone: str,
    backup_stale_after_hours: int = 36,
    quote: str | None = None,
    background_description: str | None = None,
    weather_icon: Image.Image | None = None,
) -> bytes:
    output = BytesIO()
    render_tablet_dashboard(
        snapshot,
        background,
        width=width,
        height=height,
        timezone=timezone,
        backup_stale_after_hours=backup_stale_after_hours,
        quote=quote,
        background_description=background_description,
        weather_icon=weather_icon,
    ).save(output, format="PNG", optimize=True)
    return output.getvalue()
