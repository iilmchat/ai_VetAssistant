# Отчёт по релизу v1.14.0

**Дата отчёта:** 2026-11-16
**Релиз:** v1.14.0 — «Память и карточки пациентов»
**Тег:** `v1.14.0`
**Коммит:** `0796c6cc99be56f4959ccc139bd1557c2c97c44c`
**GitHub Release:** https://github.com/iilmchat/ai_VetAssistant/releases/tag/v1.14.0
**Опубликован:** 2026-11-16 14:35 MSK (11:35 UTC)

## 1. Что вошло в релиз

Релиз закрывает блок T-160…T-165: ассистент перестал быть stateless-ботом.

| Задача | Содержание | Статус |
|---|---|---|
| T-160 | Таблицы `patients` и `episodes`, pgvector `vector(384)`, HNSW, SQLite-фолбэк, миграция `scripts/migrations/2026-11-16_patients.sql` | ✅ |
| T-161 | API карточек: `GET/POST /v1/patients`, `PATCH /v1/patients/{id}`, `GET /v1/patients/{id}/history` с пагинацией | ✅ |
| T-162 | `PatientMemory`: профиль + 5 последних + до 3 семантически близких эпизодов, бюджет 1200 символов, сохранение выжимки после ответа (включая SSE) | ✅ |
| T-163 | Agentic-создание: инструмент `create_patient`, дедупликация по кличке и виду, `age` → дата рождения | ✅ |
| T-164 | UI: селектор «Мой питомец», модалка карточки с историей, `patient_id` во всех запросах, i18n RU/EN | ✅ |
| T-165 | Версия, CHANGELOG, README, DEPLOYMENT, SECURITY, зелёный CI, тег | ✅ |

Ключевые инфраструктурные изменения: прод-БД переведена на
`pgvector/pgvector:pg16`; миграция применяется до деплоя; добавлена
зависимость `pgvector>=0.3.0`.

## 2. Проверки

### CI на коммите `0796c6c`

Run: https://github.com/iilmchat/ai_VetAssistant/actions/runs/43855529742

| Job | Результат | Время (UTC) |
|---|---|---|
| Docker Build | ✅ success | 11:11:47–11:27:34 |
| Lint & Test (`ruff`, `mypy`, `pytest`) | ✅ success | 11:27:37–11:33:32 |
| Frontend (`lint`, `test`, `build`) | ✅ success | 11:33:41–11:34:11 |

### Локальный прогон (по данным CHANGELOG)

- Python: `pytest` — **921 тест**; `ruff check .`, `mypy app` — чисто.
- Frontend: `npm run test` — **114 тестов**; `npm run lint`,
  `npm run build` — без ошибок.

## 3. Релиз и деплой

| Workflow | Run | Результат |
|---|---|---|
| Release (GitHub Release) | https://github.com/iilmchat/ai_VetAssistant/actions/runs/43858990800 | ✅ success, 27 с |
| Deploy to VPS | https://github.com/iilmchat/ai_VetAssistant/actions/runs/43858990732 | ✅ success |

Деплой собрал образы `vetassistant:1.14.0` и
`vetassistant-frontend:1.14.0`, пересоздал `api`, `bot`, `frontend`,
дождался `Healthy` у БД и API. Контейнеры `api`, `bot`, `frontend`
запущены, orphan-процессы удалены.

### Состояние прода на момент отчёта

Проверено `GET https://app.ai-pets.ru/api/health` и
`GET https://app.ai-pets.ru/api/openapi.json`:

```json
{
  "status": "ok",
  "model": "qwen3-8b-vet",
  "model_path_exists": true,
  "backend": "cpu",
  "gpu_backend": {"enabled": true, "available": false}
}
```

```json
{"title": "VetAssistant API", "version": "1.14.0"}
```

Прод отвечает, версия API — `1.14.0`; активен CPU-бэкенд, GPU включён в
конфиге, но недоступен — сработал штатный fallback.

## 4. Инциденты и замечания

1. **T-167 — «грязное» дерево на сервере.** Во время выкладки
   `git pull --ff-only` на `/srv/vetassistant` упал из-за локальных правок
   compose-файлов (сисадмин вручную менял образ БД на
   `pgvector/pgvector:pg16`). Деплой был завершён после устранения
   расхождения; защита от повторения вынесена в T-167 (v1.15.0).
2. **T-169 — критический баг логики инструментов.** На «Создай карточку
   Мурзика» `create_patient` не инжектился: триггеры T-163 ловили только
   «у меня», «мой», «зовут». Модель вызывала единственный доступный
   инструмент — `book_appointment`. Исправлено в v1.14.1.
3. **T-168 — вёрстка.** Переключатели в сайдбаре выезжали за карточку,
   у поля ввода чата появлялась красная обводка валидации. Исправлено в
   v1.14.1.
4. **T-166 — retention эпизодов.** Автоочистка старше 180 дней в v1.14.0
   не реализована; действует ручное правило ≤ 500 символов и каскадное
   удаление вместе с пользователем. Запланировано на v1.15.0.

## 5. Итог и следующий шаг

Релиз v1.14.0 состоялся: CI, Release и Deploy зелёные, прод отдаёт
`1.14.0`, память и карточки доступны в интерфейсе. Приёмочное
тестирование выявило два дефекта (T-168, T-169), они закрыты хотфиксом
**v1.14.1** — см. [RELEASE_v1.14.1.md](RELEASE_v1.14.1.md).

**Следующий шаг:** T-166 (retention эпизодов) и T-167 (защита деплоя от
локальных правок) в v1.15.0.
