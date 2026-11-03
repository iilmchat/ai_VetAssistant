"""Оркестратор production-деплоя VetAssistant на VPS (T-042).

Запуск с Windows::

    python scripts/deploy_prod.py

Скрипт использует Paramiko: подключается по SSH, выполняет базовую настройку
Ubuntu, клонирует/обновляет репозиторий, создаёт `.env` со случайными
секретами, собирает production-стек, загружает GGUF-модель через SFTP и
выпускает SSL-сертификат Let's Encrypt.

Пароль root запрашивается через ``getpass`` и нигде не сохраняется.
Токен Telegram и email для Let's Encrypt можно передать аргументами или
переменными окружения; по умолчанию используется домен ``ai-pets.ru``.
"""

from __future__ import annotations

import argparse
import codecs
import contextlib
import getpass
import logging
import os
import posixpath
import secrets
import shlex
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import paramiko

DEFAULT_HOST = "62.109.1.230"
DEFAULT_DOMAIN = "ai-pets.ru"
DEFAULT_EMAIL = "admin@ai-pets.ru"
DEFAULT_REPO = "https://github.com/iilmchat/ai_VetAssistant.git"
DEFAULT_BRANCH = "main"
REMOTE_DIR = "/opt/vetassistant"
MODEL_FILE = "data/gguf/qwen3-8b-vet-Q4_K_M.gguf"
PROJECT_ROOT = Path(__file__).resolve().parents[1]

COMPOSE_BASE = "docker compose -f docker-compose.prod.yml"
COMPOSE_SSL = "docker compose -f docker-compose.prod.yml -f docker-compose.ssl.yml"
CERT_REMOTE = "deploy/certbot/conf/live/vetassistant/fullchain.pem"

REQUIRED_ENV_KEYS = (
    "POSTGRES_PASSWORD",
    "VET_API_JWT_SECRET",
    "VET_BOT_AUTH_SECRET",
    "TELEGRAM_BOT_TOKEN",
)

logger = logging.getLogger("vetassistant.deploy")


class DeployError(RuntimeError):
    """Ошибка, после которой деплой нужно остановить."""


@dataclass(frozen=True)
class CommandResult:
    """Результат удалённой команды."""

    exit_code: int
    output: str


def configure_output() -> None:
    """Включить UTF-8 в консоли Windows, если это возможно."""
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
    logging.getLogger("paramiko").setLevel(logging.WARNING)


def run_command(
    client: paramiko.SSHClient,
    command: str,
    *,
    check: bool = True,
    timeout: float | None = None,
) -> CommandResult:
    """Выполнить команду на сервере, транслируя вывод в консоль.

    ``channel.set_combine_stderr(True)`` не даёт зависнуть, если apt/docker
    пишут прогресс в stderr. Вывод декодируется инкрементально, чтобы
    многобайтовые UTF-8 символы не ломались на границах пакетов.
    """
    logger.info("$ %s", command)
    stdin, stdout, _ = client.exec_command(command, timeout=timeout)
    stdin.close()
    channel = stdout.channel
    channel.set_combine_stderr(True)
    if timeout is not None:
        channel.settimeout(timeout)

    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    chunks: list[str] = []

    while True:
        if channel.recv_ready():
            data = channel.recv(65536)
            if not data:
                break
            text = decoder.decode(data)
            if text:
                chunks.append(text)
                sys.stdout.write(text)
                sys.stdout.flush()
        elif channel.exit_status_ready():
            while channel.recv_ready():
                text = decoder.decode(channel.recv(65536))
                if text:
                    chunks.append(text)
                    sys.stdout.write(text)
                    sys.stdout.flush()
            break
        elif channel.closed:
            break
        else:
            time.sleep(0.05)

    exit_code = channel.recv_exit_status()
    result = CommandResult(exit_code=exit_code, output="".join(chunks))
    if check and exit_code != 0:
        raise DeployError(f"команда завершилась с кодом {exit_code}: {command}")
    return result


def connect(host: str, port: int, username: str, password: str) -> paramiko.SSHClient:
    """Открыть SSH-соединение с автоматическим принятием host key."""
    logger.info("Подключение к %s@%s:%s", username, host, port)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=host,
            port=port,
            username=username,
            password=password,
            timeout=30,
            banner_timeout=30,
            auth_timeout=30,
            look_for_keys=False,
            allow_agent=False,
        )
    except (paramiko.SSHException, OSError) as exc:
        client.close()
        raise DeployError(f"не удалось подключиться по SSH: {exc}") from exc
    transport = client.get_transport()
    if transport is not None:
        transport.set_keepalive(30)
    logger.info("SSH-соединение установлено")
    return client


def ensure_remote_dir(sftp: paramiko.SFTPClient, path: str) -> None:
    """Создать удалённый каталог рекурсивно."""
    current = ""
    for part in path.strip("/").split("/"):
        current = f"{current}/{part}"
        try:
            sftp.stat(current)
        except OSError:
            sftp.mkdir(current)


def read_remote_text(sftp: paramiko.SFTPClient, path: str) -> str:
    with sftp.open(path, "r") as remote:
        data: bytes = remote.read()
    return data.decode("utf-8")


def write_remote_text(
    sftp: paramiko.SFTPClient,
    path: str,
    content: str,
    *,
    mode: int = 0o600,
) -> None:
    with sftp.open(path, "w") as remote:
        remote.write(content.encode("utf-8"))
    sftp.chmod(path, mode)


def parse_env(content: str) -> dict[str, str]:
    """Разобрать простой KEY=VALUE файл, игнорируя комментарии."""
    values: dict[str, str] = {}
    for line in content.splitlines():
        key, separator, value = line.partition("=")
        if separator and key and not key.startswith("#"):
            values[key] = value
    return values


def render_env(template: str, values: dict[str, str]) -> str:
    """Подставить значения в шаблон, сохранив комментарии и порядок."""
    lines: list[str] = []
    seen: set[str] = set()
    for line in template.splitlines():
        key, separator, _ = line.partition("=")
        if separator and key in values:
            lines.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            lines.append(line)
    for key, value in values.items():
        if key not in seen:
            lines.append(f"{key}={value}")
    return "\n".join(lines).rstrip() + "\n"


def read_local_env_value(key: str) -> str | None:
    """Прочитать значение из локального `.env` (для токена Telegram)."""
    path = PROJECT_ROOT / ".env"
    if not path.is_file():
        return None
    try:
        values = parse_env(path.read_text(encoding="utf-8"))
    except OSError:
        return None
    value = values.get(key, "").strip()
    return value or None


def resolve_telegram_token(explicit: str | None) -> str:
    """Найти токен бота: аргумент → env → .env → интерактивный ввод."""
    token = (
        explicit
        or os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        or read_local_env_value("TELEGRAM_BOT_TOKEN")
    )
    if token:
        return token
    if sys.stdin.isatty():
        token = getpass.getpass("Telegram bot token от @BotFather: ").strip()
    if not token:
        raise DeployError(
            "не задан TELEGRAM_BOT_TOKEN. Установите переменную окружения, "
            "передайте --telegram-token или запустите интерактивно."
        )
    return token


def install_system_packages(client: paramiko.SSHClient) -> None:
    """Обновить пакеты и установить Docker/Compose, если их ещё нет."""
    logger.info("Шаг 1/7: системные пакеты и Docker")
    run_command(
        client,
        "export DEBIAN_FRONTEND=noninteractive; NEEDRESTART_MODE=a apt-get update",
        timeout=1800,
    )
    run_command(
        client,
        "export DEBIAN_FRONTEND=noninteractive; "
        "NEEDRESTART_MODE=a apt-get -y -o Dpkg::Options::=--force-confdef "
        "-o Dpkg::Options::=--force-confold upgrade",
        timeout=3600,
    )
    run_command(
        client,
        "export DEBIAN_FRONTEND=noninteractive; "
        "apt-get install -y --no-install-recommends "
        "ca-certificates curl gnupg git openssl",
        timeout=1800,
    )

    ready = run_command(
        client,
        "command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1",
        check=False,
    )
    if ready.exit_code == 0:
        logger.info("Docker и Compose уже установлены — пропускаю установку")
    else:
        logger.info("Устанавливаю Docker Engine и Compose plugin")
        run_command(
            client,
            "install -m 0755 -d /etc/apt/keyrings && "
            "curl -fsSL https://download.docker.com/linux/ubuntu/gpg "
            "-o /etc/apt/keyrings/docker.asc && "
            "chmod a+r /etc/apt/keyrings/docker.asc",
            timeout=600,
        )
        run_command(
            client,
            'echo "deb [arch=$(dpkg --print-architecture) '
            "signed-by=/etc/apt/keyrings/docker.asc] "
            "https://download.docker.com/linux/ubuntu "
            '$(. /etc/os-release && echo "$VERSION_CODENAME") stable" '
            "> /etc/apt/sources.list.d/docker.list",
            timeout=120,
        )
        run_command(
            client,
            "export DEBIAN_FRONTEND=noninteractive; apt-get update",
            timeout=1800,
        )
        run_command(
            client,
            "export DEBIAN_FRONTEND=noninteractive; "
            "apt-get install -y --no-install-recommends "
            "docker-ce docker-ce-cli containerd.io "
            "docker-buildx-plugin docker-compose-plugin",
            timeout=1800,
        )

    run_command(
        client,
        "systemctl enable --now docker >/dev/null 2>&1 || true",
        timeout=120,
    )
    check = run_command(
        client,
        "docker compose version",
        check=False,
        timeout=120,
    )
    if check.exit_code != 0:
        raise DeployError("Docker Compose plugin не установился")


def sync_repository(
    client: paramiko.SSHClient,
    *,
    repo_url: str,
    branch: str,
) -> None:
    """Склонировать репозиторий или обновить существующий клон."""
    logger.info("Шаг 2/7: репозиторий %s", REMOTE_DIR)
    quoted_dir = shlex.quote(REMOTE_DIR)
    quoted_repo = shlex.quote(repo_url)
    quoted_branch = shlex.quote(branch)

    has_git = run_command(
        client,
        f"test -d {quoted_dir}/.git",
        check=False,
        timeout=60,
    )
    if has_git.exit_code == 0:
        logger.info("Репозиторий уже существует — выполняю git pull")
        run_command(
            client,
            f"cd {quoted_dir} && git fetch --prune origin && "
            f"git checkout {quoted_branch} && "
            f"git pull --ff-only origin {quoted_branch}",
            timeout=600,
        )
        return

    non_empty = run_command(
        client,
        f'test -d {quoted_dir} && [ -n "$(ls -A {quoted_dir})" ]',
        check=False,
        timeout=60,
    )
    if non_empty.exit_code == 0:
        raise DeployError(
            f"каталог {REMOTE_DIR} существует, не пуст и не является git-репозиторием"
        )

    run_command(client, f"mkdir -p {REMOTE_DIR}", timeout=60)
    run_command(
        client,
        f"git clone --branch {quoted_branch} {quoted_repo} {quoted_dir}",
        timeout=1800,
    )


def ensure_env(
    sftp: paramiko.SFTPClient,
    *,
    domain: str,
    email: str,
    telegram_token: str,
) -> None:
    """Создать `.env` из production-шаблона или проверить существующий."""
    logger.info("Шаг 3/7: production .env")
    env_path = posixpath.join(REMOTE_DIR, ".env")
    template_path = posixpath.join(REMOTE_DIR, ".env.production.example")

    try:
        existing = read_remote_text(sftp, env_path)
    except OSError:
        existing = ""

    if existing:
        values = parse_env(existing)
        missing = [key for key in REQUIRED_ENV_KEYS if not values.get(key)]
        if missing:
            raise DeployError(
                "существующий .env не содержит обязательных значений: "
                + ", ".join(missing)
                + ". Заполните его вручную и повторите запуск."
            )
        logger.info(".env уже существует — секреты не перезаписываю")
        return

    template = read_remote_text(sftp, template_path)
    generated = {
        "POSTGRES_PASSWORD": secrets.token_hex(32),
        "VET_API_JWT_SECRET": secrets.token_hex(32),
        "VET_BOT_AUTH_SECRET": secrets.token_hex(32),
        "VET_DOMAIN": domain,
        "LETSENCRYPT_EMAIL": email,
        "TELEGRAM_BOT_TOKEN": telegram_token,
    }
    write_remote_text(sftp, env_path, render_env(template, generated))
    logger.info("Создан .env с новыми случайными секретами (chmod 600)")


def upload_model(
    sftp: paramiko.SFTPClient,
    *,
    local_path: Path,
    remote_dir: str,
) -> bool:
    """Загрузить GGUF-модель через SFTP с прогресс-баром.

    Returns:
        True, если файл был загружен; False, если он уже есть нужного размера.
    """
    filename = local_path.name
    remote_path = posixpath.join(remote_dir, MODEL_FILE.rsplit("/", 1)[0], filename)
    if not local_path.is_file():
        raise DeployError(f"локальная модель не найдена: {local_path}")

    local_size = local_path.stat().st_size
    try:
        remote_size = sftp.stat(remote_path).st_size
    except OSError:
        remote_size = -1

    if remote_size == local_size:
        logger.info(
            "Модель уже загружена (%s байт) — пропускаю SFTP",
            f"{local_size:,}".replace(",", " "),
        )
        return False

    logger.info(
        "Загружаю модель %.2f ГБ → %s",
        local_size / (1024**3),
        remote_path,
    )
    sftp_channel = sftp.get_channel()
    if sftp_channel is not None:
        sftp_channel.settimeout(600)
    progress = UploadProgress(filename)

    def progress_bar(transferred: int, total: int) -> None:
        progress.update(transferred, total)

    sftp.put(str(local_path), remote_path, callback=progress_bar, confirm=True)
    sftp.chmod(remote_path, 0o644)
    logger.info("Модель загружена")
    return True


class UploadProgress:
    """Прогресс SFTP-загрузки без спама в консоль (шаг 1%)."""

    def __init__(self, filename: str, *, width: int = 32) -> None:
        self.filename = filename
        self.width = width
        self.last_percent = -1

    def update(self, transferred: int, total: int) -> None:
        percent = 100 if total <= 0 else int(transferred * 100 / total)
        if percent == self.last_percent and transferred < total:
            return
        self.last_percent = percent
        filled = int(self.width * percent / 100)
        bar = "#" * filled + "-" * (self.width - filled)
        sys.stdout.write(
            f"\r  {self.filename}: [{bar}] {percent:3d}% ({transferred / (1024**2):.1f} МБ)"
        )
        sys.stdout.flush()
        if transferred >= total:
            sys.stdout.write("\n")


def wait_for_frontend(client: paramiko.SSHClient) -> None:
    """Подождать, пока frontend начнёт отвечать на healthcheck."""
    logger.info("Ожидаю готовности frontend...")
    command = (
        "for i in $(seq 1 45); do "
        "curl -fsS --max-time 3 http://127.0.0.1/healthz >/dev/null 2>&1 "
        "&& exit 0; sleep 2; done; exit 1"
    )
    result = run_command(client, command, check=False, timeout=300)
    if result.exit_code != 0:
        raise DeployError("frontend не ответил на http://127.0.0.1/healthz")
    logger.info("Frontend отвечает на /healthz")


def wait_for_api(client: paramiko.SSHClient) -> None:
    """Подождать, пока контейнер API станет healthy."""
    logger.info("Ожидаю готовности API...")
    command = (
        "for i in $(seq 1 90); do "
        "status=$(docker inspect -f "
        "'{{if .State.Health}}{{.State.Health.Status}}"
        "{{else}}{{.State.Status}}{{end}}' vetassistant-api 2>/dev/null || true); "
        '[ "$status" = healthy ] && exit 0; sleep 2; done; exit 1'
    )
    result = run_command(client, command, check=False, timeout=300)
    if result.exit_code != 0:
        raise DeployError("контейнер API не перешёл в состояние healthy")
    logger.info("API healthy")


def deploy_compose(client: paramiko.SSHClient) -> None:
    """Собрать и запустить базовый production-стек (HTTP)."""
    logger.info("Шаг 4/7: docker compose up -d --build")
    run_command(
        client,
        f"cd {shlex.quote(REMOTE_DIR)} && {COMPOSE_BASE} up -d --build",
        timeout=None,
    )
    wait_for_frontend(client)
    wait_for_api(client)


def issue_ssl_certificate(
    client: paramiko.SSHClient,
    sftp: paramiko.SFTPClient,
    *,
    domain: str,
    email: str,
) -> None:
    """Выпустить сертификат Let's Encrypt, если его ещё нет."""
    logger.info("Шаг 6/7: SSL-сертификат для %s", domain)
    cert_path = posixpath.join(REMOTE_DIR, CERT_REMOTE)
    try:
        sftp.stat(cert_path)
        logger.info("Сертификат уже существует — пропускаю certbot")
        return
    except OSError:
        pass

    command = (
        f"cd {shlex.quote(REMOTE_DIR)} && {COMPOSE_SSL} --profile tools "
        "run --rm certbot certonly --webroot -w /var/www/certbot "
        f"-d {shlex.quote(domain)} --cert-name vetassistant "
        f"--email {shlex.quote(email)} "
        "--agree-tos --no-eff-email --non-interactive"
    )
    run_command(client, command, timeout=1800)
    logger.info("Сертификат выпущен")


def restart_api(client: paramiko.SSHClient) -> None:
    """Перезапустить API, чтобы он увидел загруженную модель."""
    logger.info("Шаг 5/7: перезапуск API")
    run_command(
        client,
        f"cd {shlex.quote(REMOTE_DIR)} && {COMPOSE_BASE} restart api",
        timeout=600,
    )
    wait_for_api(client)


def ensure_data_dirs(sftp: paramiko.SFTPClient) -> None:
    """Создать каталоги для модели, ChromaDB и Certbot."""
    for relative in (
        "data/gguf",
        "data/chroma_db",
        "deploy/certbot/www",
        "deploy/certbot/conf",
    ):
        ensure_remote_dir(sftp, posixpath.join(REMOTE_DIR, relative))


def check_ssl_health(client: paramiko.SSHClient, domain: str) -> None:
    """Проверить HTTPS на сервере; ошибка не отменяет уже выполненный деплой."""
    command = (
        f"curl -fsS --max-time 15 --resolve {shlex.quote(domain)}:443:127.0.0.1 "
        f"https://{shlex.quote(domain)}/healthz"
    )
    result = run_command(client, command, check=False, timeout=60)
    if result.exit_code == 0:
        logger.info("HTTPS healthcheck успешен: https://%s", domain)
    else:
        logger.warning("HTTPS healthcheck не прошёл. Проверьте DNS/сертификат вручную.")


def deploy(args: argparse.Namespace, password: str) -> None:
    """Выполнить полный сценарий деплоя."""
    telegram_token = resolve_telegram_token(args.telegram_token)
    client = connect(args.host, args.port, args.user, password)
    sftp: paramiko.SFTPClient | None = None
    try:
        sftp = client.open_sftp()
        install_system_packages(client)
        sync_repository(client, repo_url=args.repo, branch=args.branch)
        ensure_data_dirs(sftp)
        ensure_env(
            sftp,
            domain=args.domain,
            email=args.email,
            telegram_token=telegram_token,
        )
        deploy_compose(client)

        if args.skip_model:
            logger.info("Шаг 5/7: загрузка модели пропущена (--skip-model)")
        else:
            local_model = args.model.resolve()
            logger.info("Шаг 5/7: SFTP-загрузка модели")
            uploaded = upload_model(
                sftp,
                local_path=local_model,
                remote_dir=REMOTE_DIR,
            )
            if uploaded:
                restart_api(client)
            else:
                logger.info("Перезапуск API не требуется: модель не изменилась")

        if args.skip_ssl:
            logger.info("Шаг 6/7: SSL пропущен (--skip-ssl)")
        else:
            issue_ssl_certificate(
                client,
                sftp,
                domain=args.domain,
                email=args.email,
            )
            logger.info("Шаг 7/7: включаю HTTPS-overlay")
            run_command(
                client,
                f"cd {shlex.quote(REMOTE_DIR)} && {COMPOSE_SSL} up -d",
                timeout=1200,
            )
            check_ssl_health(client, args.domain)

        logger.info("Деплой завершён успешно")
        scheme = "http" if args.skip_ssl else "https"
        logger.info("Сайт: %s://%s", scheme, args.domain)
        logger.info("Smoke-тест: python scripts/smoke_test.py")
    finally:
        if sftp is not None:
            sftp.close()
        client.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Production-деплой VetAssistant на VPS по SSH/SFTP.",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="IP или домен VPS")
    parser.add_argument("--port", type=int, default=22, help="SSH-порт")
    parser.add_argument("--user", default="root", help="SSH-пользователь")
    parser.add_argument(
        "--domain",
        default=DEFAULT_DOMAIN,
        help="Домен для HTTPS (A-запись должна указывать на VPS)",
    )
    parser.add_argument(
        "--email",
        default=DEFAULT_EMAIL,
        help="Email для Let's Encrypt",
    )
    parser.add_argument(
        "--telegram-token",
        default=None,
        help="Токен бота; лучше задать TELEGRAM_BOT_TOKEN в окружении",
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=PROJECT_ROOT / MODEL_FILE,
        help="Путь к локальному GGUF-файлу",
    )
    parser.add_argument(
        "--repo",
        default=DEFAULT_REPO,
        help="URL git-репозитория",
    )
    parser.add_argument("--branch", default=DEFAULT_BRANCH, help="Ветка")
    parser.add_argument(
        "--skip-model",
        action="store_true",
        help="Не загружать модель (уже есть на сервере)",
    )
    parser.add_argument(
        "--skip-ssl",
        action="store_true",
        help="Не выпускать сертификат и не включать HTTPS",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_output()
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.skip_model and not args.model.resolve().is_file():
        logger.error("Локальная модель не найдена: %s", args.model.resolve())
        return 2

    password = getpass.getpass(f"Пароль {args.user}@{args.host}: ")
    if not password:
        logger.error("Пароль не введён")
        return 2

    try:
        deploy(args, password)
    except DeployError as exc:
        logger.error("Деплой остановлен: %s", exc)
        return 1
    except KeyboardInterrupt:
        logger.warning("Деплой прерван пользователем")
        return 130
    except (paramiko.SSHException, OSError) as exc:
        logger.error("Сетевая ошибка деплоя: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
