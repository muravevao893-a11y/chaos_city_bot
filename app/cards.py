from __future__ import annotations

from io import BytesIO
from typing import Any

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover - optional runtime dependency
    Image = None
    ImageDraw = None
    ImageFont = None


def _font(size: int, bold: bool = False):
    if ImageFont is None:
        return None
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _wrap(text: str, max_len: int) -> list[str]:
    words = str(text or "").split()
    lines: list[str] = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 <= max_len:
            current = f"{current} {word}".strip()
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or ["—"]


def make_daily_card(payload: dict[str, Any]) -> bytes:
    if Image is None or ImageDraw is None:
        raise RuntimeError("Pillow is not installed")

    city = payload.get("city", {})
    width, height = 1200, 1600
    img = Image.new("RGB", (width, height), (19, 25, 38))
    draw = ImageDraw.Draw(img)

    # soft background blocks
    draw.rounded_rectangle((60, 60, width - 60, height - 60), radius=48, fill=(30, 38, 56), outline=(74, 92, 130), width=3)
    draw.rounded_rectangle((90, 90, width - 90, 330), radius=36, fill=(44, 55, 78))
    draw.rounded_rectangle((90, 360, width - 90, height - 100), radius=36, fill=(25, 32, 48), outline=(52, 66, 94), width=2)

    title_font = _font(64, True)
    h_font = _font(40, True)
    body_font = _font(34)
    small_font = _font(28)

    y = 120
    draw.text((120, y), "🏙 Итоги дня", font=title_font, fill=(255, 231, 150))
    y += 86
    draw.text((120, y), str(city.get("name", "Чатоград"))[:32], font=h_font, fill=(242, 247, 255))
    y += 58
    rank = f"{city.get('rank', 'Район')} · ур. {city.get('level', 1)} · казна {city.get('treasury', 0)} · жители {city.get('population', 0)}"
    draw.text((120, y), rank, font=small_font, fill=(181, 197, 224))

    y = 410
    entries = []
    if payload.get("richest"):
        entries.append(("💰 Богач дня", f"{payload['richest']['name']} · {payload['richest']['coins']} монет"))
    if payload.get("suspect"):
        entries.append(("🕵️ Подозреваемый", f"{payload['suspect']['name']} · судимости {payload['suspect']['convictions']}"))
    if payload.get("top"):
        hero = payload["top"][0]
        entries.append(("⭐ Герой дня", f"{hero['name']} — {hero['title']}"))
    if payload.get("actions"):
        entries.append(("🔥 Движ", f"{payload['actions']} действий за сутки"))

    for label, value in entries[:6]:
        draw.rounded_rectangle((120, y, width - 120, y + 135), radius=28, fill=(38, 48, 70))
        draw.text((150, y + 22), label, font=h_font, fill=(255, 231, 150))
        draw.text((150, y + 76), value[:52], font=body_font, fill=(238, 244, 255))
        y += 160

    logs = payload.get("logs") or []
    if logs:
        draw.text((130, y + 10), "📜 Последнее", font=h_font, fill=(255, 231, 150))
        y += 70
        for item in logs[:4]:
            for line in _wrap(str(item.get("text", "")), 44)[:2]:
                draw.text((150, y), "• " + line, font=small_font, fill=(214, 225, 245))
                y += 40
            y += 10

    draw.text((120, height - 165), "Чатоград", font=h_font, fill=(255, 231, 150))
    draw.text((120, height - 115), "твой чат стал районом", font=small_font, fill=(181, 197, 224))

    buffer = BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
