"""Тесты конвертации merged-модели в GGUF (T-018).

Все тяжелые процессы замоканы: тесты проверяют формирование команд для
llama.cpp, dry-run и последовательность subprocess-вызовов.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts.convert_to_gguf import (
    BASE_NAME,
    LLAMA_CPP_REPO,
    QUANT_TYPES,
    GGUFConversionError,
    build_clone_command,
    build_cmake_build_command,
    build_cmake_configure_command,
    build_convert_command,
    build_install_command,
    build_quantize_command,
    convert_to_gguf,
    main,
    parse_args,
)


def _model_dir(tmp_path: Path) -> Path:
    model = tmp_path / "merged-model"
    model.mkdir()
    (model / "config.json").write_text("{}", encoding="utf-8")
    return model


def _fake_llama(tmp_path: Path) -> Path:
    llama = tmp_path / "llama.cpp"
    llama.mkdir()
    (llama / "convert_hf_to_gguf.py").write_text("# fake", encoding="utf-8")
    (llama / "requirements.txt").write_text("", encoding="utf-8")
    return llama


def test_build_clone_command() -> None:
    llama = Path("models/llama.cpp")
    command = build_clone_command(llama)

    assert command == ["git", "clone", LLAMA_CPP_REPO, str(llama)]
    assert LLAMA_CPP_REPO == "https://github.com/ggerganov/llama.cpp"


def test_build_install_and_convert_commands(tmp_path: Path) -> None:
    llama = tmp_path / "llama.cpp"
    model = tmp_path / "merged-model"
    output = tmp_path / "out.gguf"

    install = build_install_command(llama)
    convert = build_convert_command(llama, model, output)

    assert install[1:4] == ["-m", "pip", "install"]
    assert str(llama / "requirements.txt") in install
    assert str(llama / "convert_hf_to_gguf.py") in convert
    assert str(model) in convert
    assert convert[-2:] == ["--outtype", "f16"]


def test_build_quantize_and_cmake_commands(tmp_path: Path) -> None:
    llama = tmp_path / "llama.cpp"
    build = llama / "build"
    binary = build / "bin" / "llama-quantize"
    f16 = tmp_path / "f16.gguf"
    output = tmp_path / "q4.gguf"

    quantize = build_quantize_command(binary, f16, output, "Q4_K_M")
    configure = build_cmake_configure_command(llama, build)
    compile_command = build_cmake_build_command(build)

    assert quantize == [str(binary), str(f16), str(output), "Q4_K_M"]
    assert configure[:3] == ["cmake", "-S", str(llama)]
    assert "-DCMAKE_BUILD_TYPE=Release" in configure
    assert compile_command[:4] == ["cmake", "--build", str(build), "--config"]
    assert "llama-quantize" in compile_command


def test_dry_run_does_not_call_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    model = _model_dir(tmp_path)
    output = tmp_path / "gguf"
    llama = tmp_path / "llama.cpp"

    def fail_run(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("subprocess.run не должен вызываться в --dry-run")

    monkeypatch.setattr("scripts.convert_to_gguf.subprocess.run", fail_run)

    exit_code = main(
        [
            "--dry-run",
            "--model-dir",
            str(model),
            "--output-dir",
            str(output),
            "--llama-dir",
            str(llama),
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "git clone" in captured
    assert "convert_hf_to_gguf.py" in captured
    assert "llama-quantize" in captured
    assert "Q4_K_M" in captured
    assert "Q5_K_M" in captured
    assert not output.exists()


def test_convert_to_gguf_calls_expected_subprocesses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _model_dir(tmp_path)
    llama = _fake_llama(tmp_path)
    output = tmp_path / "gguf"
    quantize_bin = llama / "build" / "bin" / "llama-quantize"
    quantize_bin.parent.mkdir(parents=True)
    quantize_bin.write_text("", encoding="utf-8")

    calls: list[tuple[list[str], Path | None]] = []

    def fake_run(
        command: list[str],
        *,
        cwd: Path | None = None,
        check: bool = False,
    ) -> SimpleNamespace:
        assert check is True
        calls.append((command, cwd))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("scripts.convert_to_gguf.subprocess.run", fake_run)

    outputs = convert_to_gguf(model, output, llama)

    assert [path.name for path in outputs] == [
        f"{BASE_NAME}-{quant_type}.gguf" for quant_type in QUANT_TYPES
    ]
    assert all(path.parent == output for path in outputs)
    assert calls[0][0][1:4] == ["-m", "pip", "install"]
    assert calls[0][1] == llama
    assert "convert_hf_to_gguf.py" in str(calls[1][0])
    assert calls[1][0][-2:] == ["--outtype", "f16"]
    assert calls[2][0][0] == str(quantize_bin)
    assert calls[2][0][-1] == "Q4_K_M"
    assert calls[3][0][-1] == "Q5_K_M"


def test_missing_model_dir_is_reported(tmp_path: Path) -> None:
    with pytest.raises(GGUFConversionError, match="merged-модели"):
        convert_to_gguf(
            tmp_path / "absent",
            tmp_path / "gguf",
            tmp_path / "llama.cpp",
            dry_run=True,
        )


def test_missing_config_is_reported(tmp_path: Path) -> None:
    model = tmp_path / "merged-model"
    model.mkdir()

    with pytest.raises(GGUFConversionError, match=r"config\.json"):
        convert_to_gguf(model, tmp_path / "gguf", tmp_path / "llama.cpp", dry_run=True)


def test_parse_args_defaults() -> None:
    args = parse_args([])

    assert args.dry_run is False
    assert args.model_dir.name == "merged-model"
    assert args.output_dir.name == "gguf"


def test_missing_model_cli_returns_one(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "--dry-run",
            "--model-dir",
            str(tmp_path / "absent"),
            "--output-dir",
            str(tmp_path / "gguf"),
            "--llama-dir",
            str(tmp_path / "llama.cpp"),
        ]
    )

    assert exit_code == 1
    assert "merged-модели" in capsys.readouterr().out
