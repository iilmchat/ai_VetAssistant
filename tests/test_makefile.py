"""Проверки целей Makefile для GPU-сервера (T-017)."""

from __future__ import annotations

from pathlib import Path

import pytest

MAKEFILE = Path(__file__).resolve().parents[1] / "Makefile"


def _recipe(target: str) -> str:
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.strip() == f"{target}:":
            assert index + 1 < len(lines), f"у цели {target} нет рецепта"
            recipe = lines[index + 1]
            assert recipe.startswith("\t"), f"рецепт {target} должен начинаться с TAB"
            return recipe.strip()
    raise AssertionError(f"в Makefile нет цели {target}")


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("smoke", "python scripts/train_sft.py --limit 20 --max-steps 10"),
        ("train", "python scripts/train_sft.py"),
        ("merge", "python scripts/merge_lora.py"),
    ],
)
def test_makefile_targets(target: str, expected: str) -> None:
    assert _recipe(target) == expected
