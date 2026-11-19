"""Сгенерировать PNG-иконки PWA из логотипа VetAssistant (T-176).

Иконки уже лежат в `frontend/public/`; скрипт нужен только если меняется
логотип. Запуск: ``python scripts/generate_pwa_icons.py`` (нужен Pillow).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 512
BACKGROUND = "#171717"
PAW = "#34d399"

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "frontend" / "public"


def draw_paw(size: int) -> Image.Image:
    """Нарисовать иконку с лапой на тёмном фоне (с запасом для maskable)."""
    scale = 4
    canvas = Image.new("RGB", (size * scale, size * scale), BACKGROUND)
    draw = ImageDraw.Draw(canvas)

    def box(value: float) -> int:
        return int(value * size * scale)

    # Подушечка и четыре пальца — пропорции из favicon.svg.
    draw.ellipse(
        (
            box(0.28),
            box(0.44),
            box(0.72),
            box(0.82),
        ),
        fill=PAW,
    )
    toes = (
        (0.17, 0.29, 0.34, 0.45),
        (0.31, 0.20, 0.48, 0.36),
        (0.52, 0.20, 0.69, 0.36),
        (0.66, 0.29, 0.83, 0.45),
    )
    for left, top, right, bottom in toes:
        draw.ellipse(
            (box(left), box(top), box(right), box(bottom)),
            fill=PAW,
        )

    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    targets = {
        "pwa-192.png": 192,
        "pwa-512.png": 512,
        "apple-touch-icon.png": 180,
    }
    for filename, size in targets.items():
        draw_paw(size).save(OUTPUT_DIR / filename, format="PNG", optimize=True)
        print(f"saved {filename} ({size}x{size})")


if __name__ == "__main__":
    main()
