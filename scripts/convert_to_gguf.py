#!/usr/bin/env python
"""Конвертация merged Qwen3-8B в GGUF Q4_K_M / Q5_K_M (T-018).

Скрипт использует официальный llama.cpp:
- клонирует репозиторий в ``models/llama.cpp`` (если его ещё нет);
- ставит Python-зависимости конвертера;
- запускает ``convert_hf_to_gguf.py`` с ``--outtype f16``;
- собирает ``llama-quantize`` через CMake, если бинарника ещё нет;
- квантует f16 в Q4_K_M и Q5_K_M.

Все GGUF-файлы складываются в ``models/gguf``. ``--dry-run`` печатает
команды и проверяет пути, но не клонирует, не собирает и не конвертирует.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from loguru import logger

from configs.settings import PROJECT_ROOT
from data_pipeline.cli import configure_logging

LLAMA_CPP_REPO = "https://github.com/ggerganov/llama.cpp"
DEFAULT_MODEL_DIR = PROJECT_ROOT / "models" / "merged-model"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "models" / "gguf"
DEFAULT_LLAMA_DIR = PROJECT_ROOT / "models" / "llama.cpp"
BASE_NAME = "qwen3-8b-vet"
QUANT_TYPES: tuple[str, ...] = ("Q4_K_M", "Q5_K_M")
F16_NAME = f"{BASE_NAME}-f16.gguf"


class GGUFConversionError(RuntimeError):
    """Не удалось подготовить или выполнить конвертацию в GGUF."""


def build_clone_command(llama_dir: Path) -> list[str]:
    """Команда клонирования официального llama.cpp."""
    return ["git", "clone", LLAMA_CPP_REPO, str(llama_dir)]


def build_install_command(llama_dir: Path) -> list[str]:
    """Команда установки Python-зависимостей llama.cpp."""
    return [
        sys.executable,
        "-m",
        "pip",
        "install",
        "-r",
        str(llama_dir / "requirements.txt"),
    ]


def build_convert_command(llama_dir: Path, model_dir: Path, output_file: Path) -> list[str]:
    """Команда convert_hf_to_gguf.py с типом f16."""
    return [
        sys.executable,
        str(llama_dir / "convert_hf_to_gguf.py"),
        str(model_dir),
        "--outfile",
        str(output_file),
        "--outtype",
        "f16",
    ]


def build_cmake_configure_command(llama_dir: Path, build_dir: Path) -> list[str]:
    """Конфигурация CMake для сборки llama-quantize."""
    return [
        "cmake",
        "-S",
        str(llama_dir),
        "-B",
        str(build_dir),
        "-DCMAKE_BUILD_TYPE=Release",
    ]


def build_cmake_build_command(build_dir: Path) -> list[str]:
    """Сборка только цели llama-quantize."""
    return [
        "cmake",
        "--build",
        str(build_dir),
        "--config",
        "Release",
        "--target",
        "llama-quantize",
        "--parallel",
    ]


def build_quantize_command(
    quantize_bin: Path,
    f16_file: Path,
    output_file: Path,
    quant_type: str,
) -> list[str]:
    """Команда квантования llama-quantize."""
    return [
        str(quantize_bin),
        str(f16_file),
        str(output_file),
        quant_type,
    ]


def find_quantize_binary(llama_dir: Path) -> Path | None:
    """Найти собранный llama-quantize в типичных путях CMake."""
    candidates = [
        llama_dir / "build" / "bin" / "llama-quantize",
        llama_dir / "build" / "bin" / "llama-quantize.exe",
        llama_dir / "build" / "bin" / "Release" / "llama-quantize.exe",
        llama_dir / "build" / "Release" / "llama-quantize.exe",
        llama_dir / "build" / "llama-quantize",
        llama_dir / "build" / "llama-quantize.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    found = shutil.which("llama-quantize")
    return Path(found) if found else None


def expected_quantize_binary(llama_dir: Path) -> Path:
    """Ожидаемый путь бинарника (для --dry-run и сообщений)."""
    build_dir = llama_dir / "build"
    if sys.platform.startswith("win"):
        return build_dir / "bin" / "Release" / "llama-quantize.exe"
    return build_dir / "bin" / "llama-quantize"


def _run(command: Sequence[str], *, cwd: Path | None = None, dry_run: bool = False) -> None:
    """Выполнить команду или только показать её в dry-run."""
    rendered = " ".join(str(part) for part in command)
    logger.info("$ {}", rendered)
    if dry_run:
        return
    subprocess.run(list(command), cwd=cwd, check=True)


def convert_to_gguf(
    model_dir: Path = DEFAULT_MODEL_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    llama_dir: Path = DEFAULT_LLAMA_DIR,
    *,
    dry_run: bool = False,
) -> list[Path]:
    """Выполнить полную цепочку конвертации и вернуть итоговые файлы.

    Raises:
        GGUFConversionError: нет модели, llama.cpp или не собрался quantize.
        subprocess.CalledProcessError: внешняя команда завершилась с ошибкой.
    """
    model_dir = model_dir.resolve()
    output_dir = output_dir.resolve()
    llama_dir = llama_dir.resolve()
    build_dir = llama_dir / "build"

    if not model_dir.is_dir():
        raise GGUFConversionError(f"папка merged-модели не найдена: {model_dir}")
    if not (model_dir / "config.json").is_file():
        raise GGUFConversionError(f"в {model_dir} нет config.json — это не HF-модель")
    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    if not llama_dir.exists():
        _run(build_clone_command(llama_dir), dry_run=dry_run)
    elif not (llama_dir / "convert_hf_to_gguf.py").is_file() and not dry_run:
        raise GGUFConversionError(
            f"{llama_dir} существует, но не похож на llama.cpp (нет convert_hf_to_gguf.py)"
        )

    if not dry_run and not (llama_dir / "requirements.txt").is_file():
        raise GGUFConversionError(f"в {llama_dir} нет requirements.txt")

    _run(build_install_command(llama_dir), cwd=llama_dir, dry_run=dry_run)

    f16_file = output_dir / F16_NAME
    _run(
        build_convert_command(llama_dir, model_dir, f16_file),
        cwd=llama_dir,
        dry_run=dry_run,
    )

    quantize_bin = find_quantize_binary(llama_dir)
    if quantize_bin is None:
        _run(build_cmake_configure_command(llama_dir, build_dir), dry_run=dry_run)
        _run(build_cmake_build_command(build_dir), dry_run=dry_run)
        quantize_bin = find_quantize_binary(llama_dir) or expected_quantize_binary(llama_dir)

    if not dry_run and not quantize_bin.is_file():
        raise GGUFConversionError(
            f"llama-quantize не найден после сборки: {quantize_bin}. "
            "Проверьте cmake/build-essential/Visual Studio Build Tools."
        )

    outputs: list[Path] = []
    for quant_type in QUANT_TYPES:
        output_file = output_dir / f"{BASE_NAME}-{quant_type}.gguf"
        _run(
            build_quantize_command(quantize_bin, f16_file, output_file, quant_type),
            cwd=llama_dir,
            dry_run=dry_run,
        )
        outputs.append(output_file)

    return outputs


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Конвертировать merged Qwen3-8B в GGUF Q4_K_M и Q5_K_M.",
        epilog="llama.cpp клонируется в models/llama.cpp; GGUF — в models/gguf.",
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=DEFAULT_MODEL_DIR,
        metavar="PATH",
        help=f"merged HF-модель (по умолчанию {DEFAULT_MODEL_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        metavar="PATH",
        help=f"каталог GGUF (по умолчанию {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--llama-dir",
        type=Path,
        default=DEFAULT_LLAMA_DIR,
        metavar="PATH",
        help=f"каталог llama.cpp (по умолчанию {DEFAULT_LLAMA_DIR})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="показать команды, не клонировать/собирать/конвертировать",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI."""
    args = parse_args(argv)
    configure_logging()

    try:
        outputs = convert_to_gguf(
            args.model_dir,
            args.output_dir,
            args.llama_dir,
            dry_run=args.dry_run,
        )
    except (GGUFConversionError, OSError, subprocess.CalledProcessError) as exc:
        logger.error("Конвертация в GGUF прервана: {}", exc)
        return 1

    if args.dry_run:
        logger.info("--dry-run: конвертация и квантование не запускались")
    else:
        for output in outputs:
            logger.info("Готово: {}", output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
