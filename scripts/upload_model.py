"""SFTP-загрузчик модели VetAssistant для инфраструктурного агента (T-043).

Скрипт намеренно не управляет Docker, Caddy и чужими сервисами. Он умеет
только одно: загрузить GGUF-модель в ``/srv/vetassistant/data/gguf/`` через
SFTP, проверить SHA-256 и атомарно переименовать ``.part`` в финальное имя.

Используется системный OpenSSH (``ssh``/``sftp``), поэтому в зависимостях
проекта не нужен Paramiko.

Примеры::

    python scripts/upload_model.py --host 62.109.1.230
    python scripts/upload_model.py --host 62.109.1.230 --identity ~/.ssh/id_ed25519
    python scripts/upload_model.py --host 62.109.1.230 \
        --local data/gguf/qwen3-8b-vet-Q4_K_M.gguf

Пароль запрашивается через getpass. Пустой пароль означает вход по
SSH-ключам/агенту. Скрипт не печатает пароль и не сохраняет его на диск.
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import hashlib
import logging
import os
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

DEFAULT_HOST = "62.109.1.230"
DEFAULT_USER = "root"
DEFAULT_PORT = 22
REMOTE_DIR = "/srv/vetassistant/data/gguf"
MODEL_FILENAME = "qwen3-8b-vet-Q4_K_M.gguf"
MODEL_EXPECTED_SIZE = 5_027_784_064
MODEL_SHA256_PREFIX = "45cccc"
MODEL_SHA256_SUFFIX = "b10b"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCAL_MODEL = PROJECT_ROOT / "data" / "gguf" / MODEL_FILENAME

logger = logging.getLogger("vetassistant.upload_model")


class UploadError(RuntimeError):
    """Ошибка загрузки, после которой скрипт останавливается."""


def configure_output() -> None:
    """Включить UTF-8 в консоли Windows."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            with contextlib.suppress(OSError, ValueError):
                reconfigure(encoding="utf-8", errors="replace")


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )


def sha256_file(path: Path) -> str:
    """Посчитать SHA-256 локального файла."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_local_model(path: Path, expected_sha256: str | None) -> str:
    """Проверить размер и хеш локальной модели."""
    if not path.is_file():
        raise UploadError(f"локальная модель не найдена: {path}")
    size = path.stat().st_size
    if size != MODEL_EXPECTED_SIZE:
        raise UploadError(
            f"размер модели {size} байт не совпадает с контрактом {MODEL_EXPECTED_SIZE} байт"
        )

    logger.info("Считаю SHA-256 локальной модели...")
    digest = sha256_file(path)
    logger.info("Локальный SHA-256: %s", digest)
    if expected_sha256:
        expected = expected_sha256.strip().lower()
        if digest != expected:
            raise UploadError(
                f"SHA-256 не совпал с --expected-sha256: локально {digest}, ожидалось {expected}"
            )
    elif not (digest.startswith(MODEL_SHA256_PREFIX) and digest.endswith(MODEL_SHA256_SUFFIX)):
        raise UploadError(
            "SHA-256 не совпал с контрактом "
            f"{MODEL_SHA256_PREFIX}...{MODEL_SHA256_SUFFIX}: локально {digest}. "
            "Если контрактный хеш сокращён, передайте полный --expected-sha256."
        )
    return digest


def parse_sha256(output: str) -> str:
    """Извлечь SHA-256 из вывода sha256sum."""
    line = output.strip().splitlines()[-1] if output.strip() else ""
    digest = line.split()[0].lower() if line else ""
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise UploadError(f"не удалось разобрать sha256sum: {line!r}")
    return digest


def build_sftp_batch(local_path: Path, remote_path: str) -> str:
    """Собрать batch-команду для OpenSSH sftp."""
    local = str(local_path).replace("\\", "/").replace('"', '\\"')
    remote = remote_path.replace('"', '\\"')
    return f'put "{local}" "{remote}"\n'


def _ssh_options(
    *,
    port: int,
    identity: Path | None,
    password: str,
) -> list[str]:
    options = [
        "-p",
        str(port),
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=20",
        "-o",
        "LogLevel=ERROR",
    ]
    if identity is not None:
        options.extend(["-i", str(identity)])
    if not password:
        # Без пароля используем только ключи/агент и не ждём интерактивный ввод.
        options.extend(["-o", "BatchMode=yes"])
    return options


@contextlib.contextmanager
def _askpass_env(password: str) -> Iterator[dict[str, str] | None]:
    """Временный SSH_ASKPASS, чтобы не передавать пароль в аргументах."""
    if not password:
        yield None
        return

    with tempfile.TemporaryDirectory(prefix="vetassistant-askpass-") as temp_dir:
        directory = Path(temp_dir)
        env = os.environ.copy()
        env["VETASSISTANT_SSH_PASSWORD"] = password
        env["SSH_ASKPASS_REQUIRE"] = "force"
        env["DISPLAY"] = ":0"

        if os.name == "nt":
            helper = directory / "askpass.py"
            helper.write_text(
                "import os, sys\n"
                "sys.stdout.write(os.environ['VETASSISTANT_SSH_PASSWORD'] + '\\n')\n",
                encoding="utf-8",
            )
            wrapper = directory / "askpass.cmd"
            wrapper.write_text(
                f'@echo off\r\n"{sys.executable}" "{helper}"\r\n',
                encoding="ascii",
            )
            env["SSH_ASKPASS"] = str(wrapper)
        else:
            helper = directory / "askpass.sh"
            helper.write_text(
                "#!/bin/sh\nprintf '%s\\n' \"$VETASSISTANT_SSH_PASSWORD\"\n",
                encoding="utf-8",
            )
            helper.chmod(0o700)
            env["SSH_ASKPASS"] = str(helper)

        yield env


def _sftp_options(
    *,
    port: int,
    identity: Path | None,
    password: str,
) -> list[str]:
    """Опции sftp: в отличие от ssh, порт задаётся заглавной -P."""
    options = _ssh_options(port=port, identity=identity, password=password)
    # _ssh_options всегда начинается с ["-p", port]; для sftp нужен -P.
    options[0] = "-P"
    return options


def _run(
    command: list[str],
    *,
    env: dict[str, str] | None,
    capture: bool = False,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    logger.info("$ %s", " ".join(shlex.quote(part) for part in command))
    try:
        return subprocess.run(
            command,
            check=True,
            text=True,
            env=env,
            capture_output=capture,
            input=input_text,
        )
    except FileNotFoundError as exc:
        raise UploadError(
            "не найден OpenSSH. Установите ssh/sftp или используйте Linux/WSL."
        ) from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise UploadError(
            f"команда завершилась с кодом {exc.returncode}" + (f": {detail}" if detail else "")
        ) from exc


def _ssh_command(
    host: str,
    user: str,
    port: int,
    identity: Path | None,
    password: str,
    env: dict[str, str] | None,
    remote_command: str,
    *,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    options = _ssh_options(port=port, identity=identity, password=password)
    return _run(
        ["ssh", *options, f"{user}@{host}", remote_command],
        env=env,
        capture=capture,
    )


def _remote_size(
    host: str,
    user: str,
    port: int,
    identity: Path | None,
    password: str,
    env: dict[str, str] | None,
    remote_path: str,
) -> int:
    result = _ssh_command(
        host,
        user,
        port,
        identity,
        password,
        env,
        f"stat -c %s {shlex.quote(remote_path)} 2>/dev/null || true",
        capture=True,
    )
    output = result.stdout.strip()
    if not output:
        return -1
    try:
        return int(output.splitlines()[-1])
    except ValueError as exc:
        raise UploadError(f"не удалось прочитать размер {remote_path}: {output!r}") from exc


def _remote_hash(
    host: str,
    user: str,
    port: int,
    identity: Path | None,
    password: str,
    env: dict[str, str] | None,
    remote_path: str,
) -> str:
    result = _ssh_command(
        host,
        user,
        port,
        identity,
        password,
        env,
        f"sha256sum {shlex.quote(remote_path)}",
        capture=True,
    )
    return parse_sha256(result.stdout)


def _move_verified(
    *,
    host: str,
    user: str,
    port: int,
    identity: Path | None,
    password: str,
    env: dict[str, str] | None,
    part_path: str,
    target_path: str,
    expected_hash: str,
) -> None:
    part_hash = _remote_hash(host, user, port, identity, password, env, part_path)
    if part_hash != expected_hash:
        _ssh_command(
            host,
            user,
            port,
            identity,
            password,
            env,
            f"rm -f {shlex.quote(part_path)}",
        )
        raise UploadError(
            f"SHA-256 загруженного .part не совпал: получено {part_hash}, ожидалось {expected_hash}"
        )

    _ssh_command(
        host,
        user,
        port,
        identity,
        password,
        env,
        f"mv -f {shlex.quote(part_path)} {shlex.quote(target_path)} "
        f"&& chmod 644 {shlex.quote(target_path)}",
    )
    target_hash = _remote_hash(host, user, port, identity, password, env, target_path)
    if target_hash != expected_hash:
        _ssh_command(
            host,
            user,
            port,
            identity,
            password,
            env,
            f"rm -f {shlex.quote(target_path)}",
        )
        raise UploadError(
            "SHA-256 целевого файла после mv не совпал: "
            f"получено {target_hash}, ожидалось {expected_hash}"
        )
    logger.info(
        "Модель проверена после mv: %s...%s",
        target_hash[:8],
        target_hash[-4:],
    )


def upload_model(
    *,
    host: str,
    user: str,
    port: int,
    identity: Path | None,
    password: str,
    local_path: Path,
    expected_sha256: str | None,
) -> bool:
    """Загрузить модель и вернуть True, если файл был обновлён."""
    logger.info("Проверяю локальную модель...")
    local_hash = validate_local_model(local_path, expected_sha256)

    target_path = f"{REMOTE_DIR}/{MODEL_FILENAME}"
    part_path = f"{target_path}.part"
    remote_dir = REMOTE_DIR

    with _askpass_env(password) as env:
        _ssh_command(
            host,
            user,
            port,
            identity,
            password,
            env,
            f"mkdir -p {shlex.quote(remote_dir)}",
        )

        target_size = _remote_size(host, user, port, identity, password, env, target_path)
        if target_size == MODEL_EXPECTED_SIZE:
            logger.info("Файл уже есть — проверяю SHA-256...")
            if _remote_hash(host, user, port, identity, password, env, target_path) == local_hash:
                logger.info("Файл на сервере валиден — загрузка не нужна")
                return False
            logger.warning("Файл повреждён — заменяю через .part")

        part_size = _remote_size(host, user, port, identity, password, env, part_path)
        if part_size == MODEL_EXPECTED_SIZE:
            logger.info("Найден .part нужного размера — проверяю SHA-256...")
            if _remote_hash(host, user, port, identity, password, env, part_path) == local_hash:
                logger.info(".part валиден — перемещаю без повторной загрузки")
                _move_verified(
                    host=host,
                    user=user,
                    port=port,
                    identity=identity,
                    password=password,
                    env=env,
                    part_path=part_path,
                    target_path=target_path,
                    expected_hash=local_hash,
                )
                return True

        logger.info(
            "Загружаю модель %.2f ГБ через SFTP → %s.part",
            MODEL_EXPECTED_SIZE / (1024**3),
            target_path,
        )
        options = _sftp_options(port=port, identity=identity, password=password)
        _run(
            ["sftp", *options, "-b", "-", f"{user}@{host}"],
            env=env,
            input_text=build_sftp_batch(local_path, part_path),
        )

        _move_verified(
            host=host,
            user=user,
            port=port,
            identity=identity,
            password=password,
            env=env,
            part_path=part_path,
            target_path=target_path,
            expected_hash=local_hash,
        )
        logger.info("Модель успешно загружена и проверена")
        return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Загрузить GGUF-модель VetAssistant на сервер по SFTP.",
    )
    parser.add_argument(
        "--host",
        default=None,
        help=f"IP или домен сервера (по умолчанию спросит; обычно {DEFAULT_HOST})",
    )
    parser.add_argument("--user", default=DEFAULT_USER, help="SSH-пользователь")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="SSH-порт")
    parser.add_argument(
        "--identity",
        type=Path,
        default=None,
        help="Путь к приватному SSH-ключу (если не используется агент)",
    )
    parser.add_argument(
        "--local",
        type=Path,
        default=DEFAULT_LOCAL_MODEL,
        help="Локальный GGUF-файл",
    )
    parser.add_argument(
        "--expected-sha256",
        default=None,
        help="Полный ожидаемый SHA-256 (опционально)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_output()
    configure_logging()
    args = build_parser().parse_args(argv)

    host = args.host or input(f"IP сервера [{DEFAULT_HOST}]: ").strip() or DEFAULT_HOST
    password = getpass.getpass(f"Пароль {args.user}@{host} (Enter — SSH-ключи): ")
    if password and os.name == "nt":
        logger.info(
            "Windows: используется SSH_ASKPASS. Если OpenSSH не поддерживает "
            "его, укажите --identity для входа по ключу."
        )

    try:
        changed = upload_model(
            host=host,
            user=args.user,
            port=args.port,
            identity=args.identity,
            password=password,
            local_path=args.local.resolve(),
            expected_sha256=args.expected_sha256,
        )
    except UploadError as exc:
        logger.error("Загрузка остановлена: %s", exc)
        return 1
    except KeyboardInterrupt:
        logger.warning("Загрузка прервана пользователем")
        return 130

    if changed:
        logger.info("Готово: модель обновлена и проверена.")
    else:
        logger.info("Готово: модель уже была на сервере и прошла проверку.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
