"""Генератор Шага A: seed-факт → вопрос владельца животного (T-003)."""

from __future__ import annotations

from loguru import logger

from configs.prompts import PromptRenderer, get_prompts
from data_pipeline.llm_client import TeacherClient
from data_pipeline.schemas import StageARecord, Topic

#: Пары кавычек, которые модель иногда добавляет вопреки промпту.
_QUOTE_PAIRS: tuple[tuple[str, str], ...] = (
    ('"', '"'),
    ("«", "»"),
    ("'", "'"),
    ("“", "”"),
)


class GenerationError(RuntimeError):
    """Учитель вернул пустой или непригодный результат."""


def clean_query(text: str) -> str:
    """Нормализовать ответ модели: одна строка, без внешних кавычек."""
    collapsed = " ".join(text.split())
    for left, right in _QUOTE_PAIRS:
        if len(collapsed) >= 2 and collapsed.startswith(left) and collapsed.endswith(right):
            return collapsed[1:-1].strip()
    return collapsed


class StageAGenerator:
    """Генерирует «сырые» вопросы владельцев из фактов справочника.

    Пример::

        generator = StageAGenerator(client)
        record = await generator.generate_query(topic, seed_text, seed_id="seed-msd-001")
    """

    def __init__(
        self,
        client: TeacherClient,
        *,
        prompts: PromptRenderer | None = None,
        temperature: float = 0.9,
        max_tokens: int = 300,
    ) -> None:
        """Создать генератор.

        Args:
            client: клиент учителя (T-002).
            prompts: библиотека промптов; по умолчанию — `configs/prompts.yaml`.
            temperature: высокая температура нужна для разнообразия формулировок.
            max_tokens: вопрос владельца короткий, 300 токенов с запасом.
        """
        if not 0.0 <= temperature <= 2.0:
            raise ValueError("temperature должна быть в диапазоне 0..2")
        if max_tokens < 1:
            raise ValueError("max_tokens должен быть >= 1")

        self._client = client
        self._prompts = prompts if prompts is not None else get_prompts()
        self._temperature = temperature
        self._max_tokens = max_tokens

    @property
    def prompts_version(self) -> int:
        """Версия библиотеки промптов (попадает в метаданные записи)."""
        return self._prompts.version

    async def generate_query(
        self,
        topic: Topic,
        seed_text: str,
        *,
        seed_id: str,
    ) -> StageARecord:
        """Сгенерировать вопрос владельца по факту из справочника.

        Args:
            topic: тема из таксономии.
            seed_text: факт из MSD Vet Manual.
            seed_id: id сида — попадает в запись и используется `--resume`.

        Raises:
            GenerationError: модель вернула пустой ответ.
            openai.OpenAIError: ошибка API (после исчерпания ретраев).
        """
        prompt = self._prompts.render_stage_a(topic=topic, seed_text=seed_text)
        logger.debug("Шаг A: seed={} topic={} промпт={} символов", seed_id, topic, len(prompt))

        result = await self._client.chat(
            [{"role": "user", "content": prompt}],
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )

        query = clean_query(result.content)
        if not query:
            raise GenerationError(f"пустой вопрос владельца для сида {seed_id!r}")

        return StageARecord(
            id=seed_id,
            topic=topic,
            seed_text=seed_text,
            user_query=query,
            model=result.model,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
            latency_s=result.latency_s,
            attempts=result.attempts,
            prompts_version=self.prompts_version,
        )
