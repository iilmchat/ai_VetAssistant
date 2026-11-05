"""Быстрый роутер и триаж входящих сообщений (T-027).

Эвристики на регулярных выражениях выполняются до генерации ответа и решают
две задачи:

* найти сообщения с угрожающими жизни симптомами;
* заблокировать попытки prompt injection.

Роутер намеренно не использует LLM: проверка должна быть дешёвой и быстрой,
чтобы тяжёлая модель не тратила время на заведомо опасные или вредоносные
запросы.

Здесь же живёт ``BackendRouter`` (T-144): выбор GPU/CPU-инференса, фоновый
probe LM Studio и circuit breaker с fallback на CPU.
"""

from __future__ import annotations

import asyncio
import re
import threading
import time
from collections.abc import AsyncIterator, Sequence
from contextlib import suppress
from typing import Any, TypedDict

from loguru import logger

from app.backends import CpuLlamaBackend, GpuHttpBackend
from app.metrics import record_backend_request, record_backend_ttft
from app.settings import AppSettings

#: Жёсткая инструкция, которая добавляется в system prompt при экстренном случае.
EMERGENCY_SYSTEM_INSTRUCTION = (
    "ВНИМАНИЕ: СИМПТОМЫ УГРОЖАЮТ ЖИЗНИ. Твой первый ответ должен начинаться "
    "со слов 'СРОЧНО ОБРАТИТЕСЬ В КЛИНИКУ' и не должен задавать уточняющих вопросов."
)


class TriageResult(TypedDict):
    """Результат быстрой классификации сообщения."""

    is_emergency: bool
    reason: str
    injection_detected: bool


#: Пары «человекочитаемая причина — регулярное выражение».
#: Регулярные выражения рассчитаны на нормализованный текст (нижний регистр,
#: одиночные пробелы), который готовит :func:`_normalize`.
_EMERGENCY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "кровотечение",
        re.compile(
            r"\b(?:кров(?:ь|и|ью|ян\w*|ав\w*|отеч\w*|оточащ\w*|оточи\w*|оточ\w*)"
            r"|окровавл\w*)\b"
        ),
    ),
    ("судороги", re.compile(r"\b(?:судорог\w*|судорожн\w*|конвульси\w*)\b")),
    ("отравление", re.compile(r"\b(?:яд(?:а|ы|ом|е|ов)?|ядовит\w*|отрав\w*)\b")),
    (
        "нарушение дыхания",
        re.compile(r"\b(?:не\s+дыш\w*|не\s+может\s+дышать|задыха\w*|удушь\w*)\b"),
    ),
    ("парацетамол", re.compile(r"\bпарацетамол\w*\b")),
    ("потеря сознания", re.compile(r"\b(?:без\s+сознания|потеря\w*\s+сознани\w*)\b")),
)

#: Контексты, где слово «кровь» не означает кровотечение. Вырезаются только
#: перед проверкой экстренности, чтобы «анализ крови» не считался аварией.
_NON_EMERGENCY_CONTEXTS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:общ\w*|биохимическ\w*|клиническ\w*|развернут\w*)?\s*"
        r"анализ\w*\s+кров\w*"
    ),
    re.compile(r"\bпоказател\w*\s+кров\w*"),
    re.compile(r"\bрезультат\w*\s+(?:анализ\w*\s+)?кров\w*"),
)

_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "игнорирование предыдущих инструкций",
        re.compile(
            r"\b(?:ignore|disregard|forget|override|bypass)\s+"
            r"(?:all\s+|any\s+|the\s+|your\s+)*"
            r"(?:previous|prior|above|earlier|system)\s+"
            r"(?:instructions?|prompts?|rules?)\b"
        ),
    ),
    (
        "игнорирование всего предыдущего текста",
        re.compile(r"\bignore\s+(?:everything|all)\s+(?:above|before)\b"),
    ),
    (
        "попытка получить системный промпт",
        re.compile(
            r"\b(?:reveal|show|print|display|output|repeat|tell\s+me)\s+"
            r"(?:me\s+)?(?:your|the)\s+(?:system\s+)?(?:prompt|instructions|rules)\b"
        ),
    ),
    (
        "повтор предыдущего текста",
        re.compile(r"\brepeat\s+(?:the\s+)?(?:text|everything|words)\s+(?:above|before)\b"),
    ),
    (
        "режим разработчика или jailbreak",
        re.compile(
            r"\b(?:jailbreak\w*|developer\s+mode|"
            r"(?:you\s+are|act\s+as|pretend\s+to\s+be)\s+(?:now\s+)?"
            r"(?:dan|an?\s+unrestricted|jailbroken))\b"
        ),
    ),
    (
        "отключение ограничений",
        re.compile(
            r"\b(?:bypass|disable|turn\s+off)\s+(?:your\s+|all\s+)?"
            r"(?:safety|restrictions?|filters?|guardrails?)\b"
        ),
    ),
    (
        "игнорирование инструкций (рус.)",
        re.compile(
            r"\b(?:игнорируй|игнорируйте|проигнорируй|проигнорируйте)\s+"
            r"(?:все\s+|любые\s+|эти\s+)?"
            r"(?:предыдущие\s+|прошлые\s+|вышеуказанные\s+|системные\s+)?"
            r"(?:инструкции|указания|правила|промпт\w*)\b"
        ),
    ),
    (
        "забывание инструкций (рус.)",
        re.compile(
            r"\b(?:забудь|забудьте|забыть)\s+(?:все\s+)?"
            r"(?:предыдущие\s+|прошлые\s+|старые\s+)?"
            r"(?:инструкции|указания|правила|промпт\w*)\b"
        ),
    ),
    (
        "вывод системного промпта (рус.)",
        re.compile(
            r"\b(?:покажи|покажите|выведи|выведите|раскрой|раскройте|"
            r"напечатай|напечатайте|повтори|повторите|скажи|скажите)\s+"
            r"(?:мне\s+)?(?:свой\s+|ваш\s+|системный\s+)*"
            r"(?:промпт\w*|системные\s+инструкции|системные\s+правила)\b"
        ),
    ),
    (
        "режим разработчика (рус.)",
        re.compile(r"\b(?:режим\s+разработчика|отвечай\s+без\s+(?:ограничений|правил|фильтров))\b"),
    ),
)


def _normalize(text: str) -> str:
    """Привести текст к нижнему регистру и схлопнуть пробелы."""
    return " ".join(text.casefold().replace("ё", "е").split())


def _matched_labels(text: str, patterns: Sequence[tuple[str, re.Pattern[str]]]) -> list[str]:
    """Вернуть причины, регулярные выражения которых сработали."""
    return [label for label, pattern in patterns if pattern.search(text)]


def _without_non_emergency_contexts(text: str) -> str:
    """Убрать словосочетания вроде «анализ крови» перед проверкой аварий."""
    for pattern in _NON_EMERGENCY_CONTEXTS:
        text = pattern.sub(" ", text)
    return text


def triage_message(user_message: str) -> TriageResult:
    """Быстро классифицировать сообщение пользователя.

    Проверка не вызывает LLM и работает за микросекунды. Инъекции и
    экстренные симптомы определяются независимо: сообщение может быть
    одновременно опасным по содержанию и содержать попытку взлома.

    Args:
        user_message: последнее сообщение пользователя.

    Returns:
        Словарь с ключами ``is_emergency``, ``reason`` и
        ``injection_detected``.
    """
    text = _normalize(user_message)
    if not text:
        return {"is_emergency": False, "reason": "", "injection_detected": False}

    emergency_labels = _matched_labels(
        _without_non_emergency_contexts(text),
        _EMERGENCY_PATTERNS,
    )
    injection_labels = _matched_labels(text, _INJECTION_PATTERNS)

    reasons: list[str] = []
    if emergency_labels:
        reasons.append(f"экстренные симптомы: {', '.join(emergency_labels)}")
    if injection_labels:
        reasons.append(f"попытка prompt injection: {', '.join(injection_labels)}")

    return {
        "is_emergency": bool(emergency_labels),
        "reason": "; ".join(reasons),
        "injection_detected": bool(injection_labels),
    }


def with_emergency_instruction(
    messages: Sequence[dict[str, str]],
) -> list[dict[str, str]]:
    """Добавить жёсткую инструкцию в system message.

    Исходный список не изменяется. Если system message отсутствует, он
    создаётся в начале списка.
    """
    result = [dict(message) for message in messages]
    for index, message in enumerate(result):
        if message.get("role") == "system":
            content = message.get("content", "").strip()
            result[index] = {
                **message,
                "content": f"{content}\n\n{EMERGENCY_SYSTEM_INSTRUCTION}".strip(),
            }
            return result

    return [{"role": "system", "content": EMERGENCY_SYSTEM_INSTRUCTION}, *result]


#: Сколько подряд ошибок GPU переводят circuit breaker в открытое состояние.
GPU_FAILURE_THRESHOLD = 3

#: Сколько секунд после открытия circuit breaker не трогаем GPU.
GPU_COOLDOWN_S = 180.0


async def _close_async_stream(stream: AsyncIterator[dict[str, Any]]) -> None:
    """Закрыть async-генератор, если он это умеет."""
    aclose = getattr(stream, "aclose", None)
    if aclose is None:
        return
    with suppress(Exception):
        await aclose()


class BackendRouter:
    """Выбирает GPU-бэкенд, а при проблемах деградирует на CPU (T-144).

    GPU считается доступным, пока фоновый probe отвечает и circuit breaker
    не открыт. После трёх подряд ошибок (probe или генерации) GPU помечается
    недоступным на ``GPU_COOLDOWN_S``; запросы в это время идут на CPU.
    Стрим переключается на CPU только до первого отданного чанка, иначе
    пользователь получил бы дубли текста.
    """

    def __init__(
        self,
        *,
        gpu: GpuHttpBackend | None,
        cpu: CpuLlamaBackend,
        settings: AppSettings,
    ) -> None:
        self._gpu = gpu
        self._cpu = cpu
        self._settings = settings
        self._gpu_available = False
        self._failures = 0
        self._cooldown_until = 0.0
        self._state_lock = threading.Lock()
        self._stop = asyncio.Event()
        self._probe_task: asyncio.Task[None] | None = None

    @property
    def gpu_enabled(self) -> bool:
        """Включён ли GPU-бэкенд настройкой и создан ли он."""
        return self._settings.gpu_backend_enabled and self._gpu is not None

    @property
    def gpu_available(self) -> bool:
        """Считает ли роутер GPU доступным прямо сейчас."""
        with self._state_lock:
            return self._gpu_available

    @property
    def name(self) -> str:
        """Имя активного бэкенда: ``gpu`` или ``cpu``."""
        return "gpu" if self._use_gpu() else "cpu"

    @property
    def active_backend_name(self) -> str:
        """Псевдоним ``name`` для healthcheck-а."""
        return self.name

    def _use_gpu(self) -> bool:
        if not self.gpu_enabled:
            return False
        with self._state_lock:
            return self._gpu_available and time.monotonic() >= self._cooldown_until

    def _in_cooldown(self) -> bool:
        with self._state_lock:
            return time.monotonic() < self._cooldown_until

    def _record_success(self) -> None:
        with self._state_lock:
            was_available = self._gpu_available
            self._gpu_available = True
            self._failures = 0
            self._cooldown_until = 0.0
        if not was_available:
            logger.info("GPU backend: доступен, переключаюсь с CPU")

    def _record_failure(self, reason: str) -> None:
        with self._state_lock:
            self._failures += 1
            failures = self._failures
            if failures >= GPU_FAILURE_THRESHOLD:
                self._gpu_available = False
                self._cooldown_until = time.monotonic() + GPU_COOLDOWN_S
        if failures >= GPU_FAILURE_THRESHOLD:
            logger.warning(
                "GPU backend: {} подряд ошибок ({}), CPU fallback на {:.0f} с",
                failures,
                reason,
                GPU_COOLDOWN_S,
            )

    async def start(self) -> None:
        """Запустить фоновый probe (только если GPU включён)."""
        if not self.gpu_enabled or self._probe_task is not None:
            return
        self._probe_task = asyncio.create_task(
            self._probe_loop(),
            name="gpu-backend-probe",
        )

    async def aclose(self) -> None:
        """Остановить probe и закрыть HTTP-клиенты бэкендов."""
        self._stop.set()
        if self._probe_task is not None:
            self._probe_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._probe_task
            self._probe_task = None
        if self._gpu is not None:
            await self._gpu.aclose()
        await self._cpu.aclose()

    async def _probe_loop(self) -> None:
        interval = self._settings.gpu_backend_probe_interval_s
        while not self._stop.is_set():
            await self.probe_once()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except TimeoutError:
                continue

    async def probe_once(self) -> bool:
        """Один probe GPU; обновляет состояние circuit breaker."""
        if not self.gpu_enabled or self._gpu is None:
            return False
        if self._in_cooldown():
            return False
        try:
            ok = await self._gpu.probe()
        except Exception as exc:
            logger.warning("GPU backend: probe упал — {}", type(exc).__name__)
            ok = False
        if ok:
            self._record_success()
        else:
            self._record_failure("probe")
        return ok

    async def _call_cpu(self, **kwargs: Any) -> dict[str, Any]:
        try:
            result = await self._cpu.create_chat_completion(**kwargs)
        except Exception:
            record_backend_request("cpu", "error")
            raise
        record_backend_request("cpu", "success")
        return result

    async def create_chat_completion(self, **kwargs: Any) -> dict[str, Any]:
        """Генерация с GPU→CPU fallback."""
        backend = self._gpu if self._use_gpu() else None
        if backend is None:
            return await self._call_cpu(**kwargs)

        try:
            result = await backend.create_chat_completion(**kwargs)
        except Exception as exc:
            record_backend_request("gpu", "error")
            self._record_failure("generation")
            logger.warning(
                "GPU backend: генерация не удалась ({}), fallback на CPU",
                type(exc).__name__,
            )
            return await self._call_cpu(**kwargs)

        record_backend_request("gpu", "success")
        return result

    async def stream_chat_completion(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        """Потоковая генерация с GPU→CPU fallback до первого чанка."""
        if self._use_gpu() and self._gpu is not None:
            yielded = False
            try:
                async for chunk in self._stream_gpu(self._gpu, **kwargs):
                    yielded = True
                    yield chunk
                return
            except Exception as exc:
                if yielded:
                    raise
                logger.warning(
                    "GPU backend: стрим не начался ({}), fallback на CPU",
                    type(exc).__name__,
                )

        async for chunk in self._stream_cpu(**kwargs):
            yield chunk

    async def _stream_gpu(
        self,
        backend: GpuHttpBackend,
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        stream = backend.stream_chat_completion(**kwargs)
        started = time.perf_counter()
        first_received = False
        try:
            try:
                first = await asyncio.wait_for(
                    stream.__anext__(),
                    timeout=self._settings.gpu_backend_ttft_fallback_s,
                )
            except StopAsyncIteration:
                record_backend_request("gpu", "success")
                return
            except Exception:
                record_backend_request("gpu", "error")
                self._record_failure("ttft")
                raise

            first_received = True
            record_backend_ttft("gpu", time.perf_counter() - started)
            yield first
            async for chunk in stream:
                yield chunk
        except Exception:
            if first_received:
                record_backend_request("gpu", "error")
                self._record_failure("stream")
            raise
        else:
            record_backend_request("gpu", "success")
        finally:
            await _close_async_stream(stream)

    async def _stream_cpu(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        stream = self._cpu.stream_chat_completion(**kwargs)
        started = time.perf_counter()
        first = True
        try:
            async for chunk in stream:
                if first:
                    record_backend_ttft("cpu", time.perf_counter() - started)
                    first = False
                yield chunk
        except Exception:
            record_backend_request("cpu", "error")
            raise
        else:
            record_backend_request("cpu", "success")
        finally:
            await _close_async_stream(stream)