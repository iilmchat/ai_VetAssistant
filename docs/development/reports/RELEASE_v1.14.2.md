# Отчёт по релизу v1.14.2

**Дата:** 2026-11-17
**Релиз:** v1.14.2 — патч памяти, `create_patient`, анти-галлюцинаций и записей
**Коммит:** `9c92a3c`
**GitHub Release:** https://github.com/iilmchat/ai_VetAssistant/releases/tag/v1.14.2
**CI:** https://github.com/iilmchat/ai_VetAssistant/actions/runs/43970489420

## 1. T-170 — падение семантического поиска (`'cosine_distance'`)

**Причина.** Колонка была объявлена как
`JSON().with_variant(Vector(384), "postgresql")`. У `with_variant` базовым
остаётся исходный тип, поэтому компаратор колонки был JSON-ный и метода
`cosine_distance` у него не было — отсюда `AttributeError: 'cosine_distance'`.

**Исправление** в [app/database.py](../../app/database.py):

```python
embedding: Mapped[list[float] | None] = mapped_column(
    Vector(MEMORY_EMBEDDING_DIM).with_variant(JSON, "sqlite"),
    nullable=True,
)
```

Теперь базовый тип — `Vector(384)` (есть `cosine_distance` и `<=>`), JSON
остаётся только для SQLite, чтобы локальные тесты шли без pgvector.
Добавлены проверки:

- `Episode.embedding.comparator` имеет `cosine_distance`;
- SQL компилируется с оператором `<=>` для PostgreSQL;
- тип для PostgreSQL — `Vector(384)`, для SQLite — `JSON`.

## 2. T-171 — `create_patient` без лишних вопросов

В [app/tools.py](../../app/tools.py) описание инструмента заменено на:

> Вызывай этот инструмент СРАЗУ, как только пользователь назвал кличку и
> вид. Не задавай вопросы про вес, вакцинацию, породу — они необязательны.

В системную инструкцию добавлено жёсткое правило: по просьбе создать
карточку вызывать `create_patient` немедленно, не задавая уточняющих
вопросов. Тест проверяет наличие этой формулировки.

## 3. T-172 — защита от ложного «Карточка создана»

В agentic loop ([app/main.py](../../app/main.py), `_complete`) добавлен guard:

1. Регулярка `_claims_card_created` распознаёт утверждения «карточка
   создана», «создал карточку», «завёл карточку», английские `card created`.
2. Отрицания («не создана», «не создал») и вопросы («создана?») не
   считаются утверждением.
3. Если утверждение есть, а успешного `create_patient` (`success`/`exists`)
   в этом ответе не было, текст заменяется на:
   **«Извините, произошла ошибка при создании карточки, попробуйте еще раз.»**

Учитывается и автосоздание карточки внутри `book_appointment` (T-173),
чтобы не заменять правдивый ответ. Streaming-путь с инструментами
использует тот же `_complete`, поэтому guard работает и в SSE.

Тесты: ложное утверждение без вызова инструмента → ответ заменён, карточка
не создана; утверждение после успешного `create_patient` → сохранено.

## 4. T-173 — запись на приём только к карточке

**Схема.** В `appointments` добавлен `patient_id`
(`ON DELETE SET NULL`) и индекс. Миграция:
[scripts/migrations/2026-11-17_appointments_patient.sql](../../scripts/migrations/2026-11-17_appointments_patient.sql).
Старые базы получают колонку в `create_tables`; существующие записи
остаются с `patient_id = NULL`.

**Логика `book_appointment`:**

1. Если передан `patient_id` — карточка ищется среди карточек пользователя;
   чужая/несуществующая → ошибка.
2. Иначе карточка ищется по кличке (+ виду, если передан).
3. Если карточки нет, но передан `species` (`dog`/`cat`) — карточка
   создаётся автоматически и запись привязывается к ней.
4. Если карточки нет и вида нет — `ToolExecutionError` с требованием
   создать карточку; запись не создаётся.

`AppointmentRead` и frontend-тип `Appointment` теперь отдают `patient_id`.
Сервер также добавляет `create_patient` в инструменты, если клиент просит
`book_appointment` без выбранной карточки, чтобы модель могла исправить
ситуацию в том же agentic loop.

Тесты: запись без карточки не создаётся; существующая карточка
привязывается; автосоздание по `species`; чужая карточка отклоняется;
legacy-миграция добавляет `patient_id`.

## 5. Проверки

| Проверка | Результат |
|---|---|
| `py -3.12 -m pytest -q` | **954 passed**, 0 failed, 0 errors |
| `py -3.12 -m ruff check .` | All checks passed |
| `py -3.12 -m mypy app` | Success: no issues in 19 source files |
| `npm run lint` | 0 warnings, 0 errors |
| `npm run test` | **114 passed** (12 files) |
| `npm run build` | success (`tsc -b` + Vite) |

Новых тестов: **+9** к v1.14.1 (954 против 945): T-170, T-171, T-172,
T-173, legacy-миграция.

## 6. CI, релиз и деплой

| Шаг | Результат | Время (UTC) |
|---|---|---|
| CI — Docker Build | ✅ success | 22:29:10–22:43:29 |
| CI — Lint & Test (`ruff`, `mypy`, `pytest`) | ✅ success | 22:43:31–22:49:21 |
| CI — Frontend (`lint`, `test`, `build`) | ✅ success | 22:49:25–22:49:55 |
| Тег `v1.14.2` | ✅ создан после зелёного CI | ~22:50 |
| GitHub Release | ✅ https://github.com/iilmchat/ai_VetAssistant/releases/tag/v1.14.2 | 22:50:44 |
| Deploy to VPS | ✅ https://github.com/iilmchat/ai_VetAssistant/actions/runs/43973851610 | 22:50:30–23:06:29 |

CI: https://github.com/iilmchat/ai_VetAssistant/actions/runs/43970489420
(коммит `9c92a3c`).

### Проверка прода

На 2026-11-17 02:06 MSK:

```json
{"title": "VetAssistant API", "version": "1.14.2"}
```

```json
{
  "status": "ok",
  "model": "qwen3-8b-vet",
  "model_path_exists": true,
  "backend": "cpu",
  "gpu_backend": {"enabled": true, "available": false}
}
```

Прод отдаёт **1.14.2**, модель на месте, CPU-бэкенд работает.
Колонка `appointments.patient_id` добавляется миграцией
`2026-11-17_appointments_patient.sql` и/или идемпотентным
`_migrate_legacy_tables` при старте API.

## 7. Миграция на проде

Перед деплоем v1.14.2 применить:

```bash
docker compose -f docker-compose.edge.yml exec -T db \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' \
  < scripts/migrations/2026-11-17_appointments_patient.sql
```

Проверка:

```bash
docker compose -f docker-compose.edge.yml exec -T db \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
         -c "\d appointments" \
         -c "SELECT count(*) FROM appointments WHERE patient_id IS NULL;"'
```

## 8. Итог

Все четыре дефекта закрыты, поведение покрыто тестами. После миграции
`appointments.patient_id` существующие записи не теряются, новые записи
создаются только с карточкой питомца.
