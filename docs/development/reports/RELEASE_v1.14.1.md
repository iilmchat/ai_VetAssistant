# Отчёт по релизу v1.14.1

**Дата:** 2026-11-16
**Релиз:** v1.14.1 — хотфикс инструментов и вёрстки
**Тег:** `v1.14.1`
**Коммит:** `176c0c6`
**GitHub Release:** https://github.com/iilmchat/ai_VetAssistant/releases/tag/v1.14.1
**CI:** https://github.com/iilmchat/ai_VetAssistant/actions/runs/43940134309
**Предыдущий релиз:** [v1.14.0](RELEASE_v1.14.0.md)

## 1. Что вошло

| Задача | Исправление | Отчёт |
|---|---|---|
| T-169 | `create_patient` инжектится на явные просьбы («создай карточку», «создать питомца», «добавь питомца», «заведи карточку»), даже при выбранной карточке и `use_patient_tools=false`; инструкция запрещает `book_appointment` вместо создания карточки | [T-168_T-169.md](T-168_T-169.md) |
| T-168 | Переключатели в сайдбаре не выезжают за карточку (flex вместо absolute+translate); у поля ввода зелёный фокус, красная обводка валидации подавлена | [T-168_T-169.md](T-168_T-169.md) |
| T-170 | Версия `1.14.1`, CHANGELOG, README, TODO, отчёты, commit/push/tag | этот файл |

## 2. Локальные проверки

| Проверка | Результат |
|---|---|
| `py -3.12 -m pytest -q` | **945 passed**, 0 failed, 0 errors |
| `py -3.12 -m ruff check .` | All checks passed |
| `py -3.12 -m mypy app` | Success: no issues in 19 source files |
| `npm run lint` | 0 warnings, 0 errors (53 files) |
| `npm run test` | **114 passed** (12 files) |
| `npm run build` | success (`tsc -b` + Vite) |
| Вёрстка | скриншоты headless Edge 320/340 px: переключатели и текст в пределах карточки, фокус зелёный |

Новых тестов: **+24** (945 против 921 в v1.14.0), все — в
`tests/test_patient_tools.py`.

## 3. CI

Run: https://github.com/iilmchat/ai_VetAssistant/actions/runs/43940134309
(коммит `176c0c6`, 2026-11-16 19:31–20:12 UTC)

| Job | Результат | Время (UTC) |
|---|---|---|
| Docker Build (API + frontend) | ✅ success | 19:31:06–20:06:11 |
| Frontend (`lint`, `test`, `build`) | ✅ success | 20:06:13–20:06:40 |
| Lint & Test (`ruff`, `mypy`, `pytest`) | ✅ success | 20:06:44–20:12:25 |

Все три job зелёные, тег создан только после успешного CI.

## 4. Релиз и деплой

| Workflow | Результат | Время (UTC) |
|---|---|---|
| Release (GitHub Release) | ✅ success — https://github.com/iilmchat/ai_VetAssistant/actions/runs/43947412538 | 20:12:51–20:29:28 |
| Deploy to VPS | ✅ success — https://github.com/iilmchat/ai_VetAssistant/actions/runs/43947412302 | 20:13:00–20:29:09 |

Тег `v1.14.1` указывает на `176c0c6`. Deploy собрал образы
`vetassistant:1.14.1` и `vetassistant-frontend:1.14.1` и пересоздал
контейнеры; API и БД перешли в `Healthy`.

## 5. Проверка прода

На 2026-11-16 23:29 MSK:

```json
{"title": "VetAssistant API", "version": "1.14.1"}
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

Прод отдаёт **1.14.1**, модель на месте, CPU-бэкенд работает; GPU
включён в конфиге, но недоступен — штатный fallback.

## 6. Итог

T-168 и T-169 закрыты, версия поднята до `1.14.1`, отчёт по v1.14.0
подготовлен отдельно. Следующие задачи релиза v1.15.0 — T-166 (retention
эпизодов) и T-167 (защита деплоя от локальных правок).
