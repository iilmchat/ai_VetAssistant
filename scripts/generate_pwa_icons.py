"""Сгенерировать иконки PWA и Android из логотипа VetAssistant (T-176, T-180).

Иконки уже лежат в `frontend/public/` и `frontend/android/app/src/main/res/`;
скрипт нужен только если меняется логотип. Запуск:
``python scripts/generate_pwa_icons.py`` (нужен Pillow).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DIR = PROJECT_ROOT / "frontend" / "public"
RES_DIR = PROJECT_ROOT / "frontend" / "android" / "app" / "src" / "main" / "res"

BACKGROUND = "#171717"
PAW = "#34d399"

# Пропорции лапы из frontend/public/favicon.svg.
PAD = (0.28, 0.44, 0.72, 0.82)
TOES = (
    (0.17, 0.29, 0.34, 0.45),
    (0.31, 0.20, 0.48, 0.36),
    (0.52, 0.20, 0.69, 0.36),
    (0.66, 0.29, 0.83, 0.45),
)

LAUNCHER_DENSITIES = {
    "mdpi": 48,
    "hdpi": 72,
    "xhdpi": 96,
    "xxhdpi": 144,
    "xxxhdpi": 192,
}

SPLASH_SIZES = {
    "drawable": (480, 320),
    "drawable-land-mdpi": (800, 480),
    "drawable-land-hdpi": (1280, 720),
    "drawable-land-xhdpi": (1600, 960),
    "drawable-land-xxhdpi": (1920, 1280),
    "drawable-port-mdpi": (480, 800),
    "drawable-port-hdpi": (720, 1280),
    "drawable-port-xhdpi": (960, 1600),
    "drawable-port-xxhdpi": (1280, 1920),
}


def draw_paw(
    size: int,
    *,
    transparent: bool = False,
    background: str = BACKGROUND,
) -> Image.Image:
    """Нарисовать лапу; ``transparent`` — для adaptive-иконки."""
    scale = 4
    mode = "RGBA" if transparent else "RGB"
    fill = (0, 0, 0, 0) if transparent else background
    canvas = Image.new(mode, (size * scale, size * scale), fill)
    draw = ImageDraw.Draw(canvas)

    def box(value: float) -> int:
        return int(value * size * scale)

    color = (52, 211, 153, 255) if transparent else PAW

    draw.ellipse(tuple(box(value) for value in PAD), fill=color)
    for toe in TOES:
        draw.ellipse(tuple(box(value) for value in toe), fill=color)

    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def draw_splash(width: int, height: int) -> Image.Image:
    """Тёмный фон и центрированная лапа для экрана загрузки."""
    paw_size = int(min(width, height) * 0.38)
    paw = draw_paw(paw_size, transparent=True)
    canvas = Image.new("RGB", (width, height), BACKGROUND)
    canvas.paste(
        paw,
        ((width - paw_size) // 2, (height - paw_size) // 2),
        paw,
    )
    return canvas


def main() -> None:
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)

    for filename, size in {
        "pwa-192.png": 192,
        "pwa-512.png": 512,
        "apple-touch-icon.png": 180,
    }.items():
        draw_paw(size).save(PUBLIC_DIR / filename, format="PNG", optimize=True)
        print(f"saved {filename} ({size}x{size})")

    if not RES_DIR.exists():
        print("Android-проект не найден — пропускаю нативные иконки")
        return

    for density, size in LAUNCHER_DENSITIES.items():
        target = RES_DIR / f"mipmap-{density}"
        target.mkdir(parents=True, exist_ok=True)
        icon = draw_paw(size)
        icon.save(target / "ic_launcher.png", format="PNG", optimize=True)
        icon.save(target / "ic_launcher_round.png", format="PNG", optimize=True)
        foreground = draw_paw(int(size * 1.5), transparent=True)
        foreground.save(
            target / "ic_launcher_foreground.png",
            format="PNG",
            optimize=True,
        )

    for folder, (width, height) in SPLASH_SIZES.items():
        target = RES_DIR / folder
        target.mkdir(parents=True, exist_ok=True)
        draw_splash(width, height).save(
            target / "splash.png",
            format="PNG",
            optimize=True,
        )
    print("saved Android launcher and splash icons")


if __name__ == "__main__":
    main()
