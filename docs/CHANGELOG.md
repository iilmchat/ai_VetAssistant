# Changelog

Все заметные изменения проекта VetAssistant.
Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.0.0/),
версии — по [Semantic Versioning](https://semver.org/lang/ru/).

## [1.13.0] — 2026-11-16

Каркас DPO-датасета из оценок 👍/👎 (T-155) и расширение RAG десятью
статьями MSD Vet Manual по узким темам (T-156).

### Добавлено

- **T-155.1 — `scripts/build_dpo_dataset.py`.** Собирает
  `data/dpo/train.jsonl`, `val.jsonl` и `manifest.json` из таблицы
  `feedback` или готового JSONL (`--input`). Сплит 80/20 детерминирован
  (`seed=42`, сортировка по SHA-256 от `message_id`); повторные оценки
  одного сообщения дедуплицируются — остаётся самая свежая. В каждой
  строке только `{"message_id", "rating", "split"}`: текстов диалогов и
  `user_id` в датасете нет (152-ФЗ). Поддержаны `--database-url`,
  `--output-dir`, `--train-ratio`, `--seed`, `--since`, `--until`,
  `--rating`, `--limit`, `--dry-run`; коды выхода 0/1/2.
- **T-155.2 — `tests/test_build_dpo_dataset.py`.** 25 тестов: 80/20,
  детерминированность, дедупликация, фильтры, режим JSONL без БД, пустая
  БД, битый JSONL, неверный `--train-ratio` и взаимоисключающие
  `--input`/`--database-url`.
- **T-156 — 10 новых статей MSD Vet Manual.** Стоматология собак и кошек,
  глаукома собак, гипо-/гипертиреоз, аллергии собак, лишай кошек,
  остеоартроз, хроническая болезнь почек и астма/бронхит кошек. Набор
  воспроизводим: `python scripts/download_msd.py --batch expansion`
  (каталог `EXPANSION_ARTICLES`, `--batch all` — базовые и новые статьи).
  Корпус вырос с 17 до 27 статей, индекс — с 766 до **904 чанков**.
- **T-156 — 27 контрольных вопросов RAG.** В `evaluate_hybrid_rag.py`
  добавлены 10 вопросов по новым темам; в `RU_EN_TERMS` — термины
  `глаукома`, `щитовидная`, `гипотиреоз`, `гипертиреоз`, `астма`,
  `бронхит`, `пародонт`, `десны`, `остеоартроз`, `дерматофит`, `лишай` и
  другие. Офлайн-BM25 с глоссарием — **27/27 (100 %)**, MRR 0.938;
  регрессии на старых 17 вопросах нет. Отчёт:
  `data/rag_hybrid_eval_v1130.json`, `docs/development/reports/RAG_EVAL.md` §9.
- **Документация.** `DEPLOYMENT.md` §«Как добавить новые статьи в RAG»:
  скачивание батчем, проверка текста, переиндексация с остановкой API,
  перезапуск для пересборки BM25 и замер `--mode both`. README обновлён
  (состав базы, 904 чанка, 27/27). TODO: T-155.1/T-155.2, T-156 закрыты;
  T-154 официально закрыта после подтверждения сисадмина.

### Изменено

- Версия `1.13.0` в `pyproject.toml`, `app/main.py`,
  `frontend/package.json`, `frontend/package-lock.json`, README и
  `tests/test_deployment.py`.

### Проверено

- Python: `pytest` — 845 тестов; `ruff check .` и `mypy app` — чисто.
- RAG: `python scripts/evaluate_hybrid_rag.py --mode bm25` — 27/27
  (100 %), MRR 0.938, 904 чанка.

## [1.12.1] — 2026-11-09

Исправление: независимый язык админ-панели (T-154.5).

### Исправлено

- **Переключатель RU/EN в админке больше не меняет язык чата.** Язык
  админки хранится отдельно — `localStorage` ключ
  `vetassistant.admin.language`; глобальный ключ `vetassistant.language`
  не затрагивается.
- **Отдельный i18n-инстанс.** Добавлены `frontend/src/lib/adminI18n.ts`,
  `frontend/src/lib/adminI18nContext.ts` и `AdminI18nProvider`: внутри
  админки `useTranslation()` читает её собственный инстанс, глобальный
  `setLanguage` не вызывается.
- **Fallback на глобальный язык.** Если `admin.language` не задан, админка
  использует язык интерфейса; кнопка «Как в чате» сбрасывает override.
- **Локальные даты и числа.** `AdminDashboard`/`AdminUsers` форматируют даты,
  а `AdminAnalytics` — метрики и проценты по языку админки.
- **Тесты.** `i18n.test.ts` дополнен проверками независимости языков,
  fallback и устойчивости к неизвестным значениям (100 тестов).

### Изменено

- Версия `1.12.1` в `pyproject.toml`, `app/main.py`, `frontend/package.json`,
  `frontend/package-lock.json`, README; обновлён `tests/test_deployment.py`.

### Проверено

- Frontend: `npm run lint` — 0 ошибок; `npm test` — 100 тестов;
  `npm run build` — успешно.
- Python: `pytest` — 814 тестов; `ruff check .` и `mypy app` — чисто.

## [1.12.0] — 2026-11-09

Светлая тема, горячие клавиши и мобильная вёрстка (T-154).

### Добавлено

- **T-154.1 — темы Light / Dark / System.** Переключатель в сайдбаре и на
  экране входа; выбор в `localStorage` (`vetassistant.theme`), «System»
  слушает `prefers-color-scheme`. По умолчанию тёмная тема — как до релиза.
  Палитра вынесена в CSS-переменные и Tailwind-токены (`bg-app`, `text-ink`,
  `border-line`, `bg-panel` и т. п.); светлая тема включается атрибутом
  `data-theme="light"`. Обновлены чат, сайдбар, модалки, Markdown, Telegram-
  привязка и все экраны админки.
- **T-154.2 — горячие клавиши.** `Ctrl/Cmd+K` фокусирует поле ввода чата,
  `Ctrl/Cmd+Enter` отправляет сообщение, `Esc` закрывает модальные окна
  (настройки, смена пароля, заявка, действия админки) и мобильный drawer.
  Логика вынесена в `frontend/src/lib/hotkeys.ts`.
- **T-154.3 — мобильная вёрстка.** Сайдбар — drawer до 768 px с гамбургером,
  затемнением и закрытием по Esc; увеличены touch-цели composer и кнопок
  оценки; добавлен `safe-area-inset-bottom`; вкладки админки прокручиваются
  по горизонтали.
- **T-154.4 — мелочи.** Переключатель RU/EN в шапке админки; spinner рядом с
  кнопкой «Стоп» при отправке/генерации ответа.
- **Тесты.** `frontend/src/lib/theme.test.ts` и `hotkeys.test.ts` — 8 тестов;
  обновлены `i18n.test.ts` и версия в `tests/test_deployment.py`.

### Изменено

- Версия `1.12.0` в `pyproject.toml`, `app/main.py`, `frontend/package.json`,
  `frontend/package-lock.json`, README.
- `README.md`: раздел v1.12.0 и статус; `TODO.md`: T-154 закрыта;
  `docs/CHANGELOG.md` — этот раздел.

### Проверено

- Frontend: `npm run lint` — 0 ошибок; `npm test` — 95 тестов;
  `npm run build` — успешно.
- Python: `pytest` — 814 тестов; `ruff check .` и `mypy app` — чисто.

## [1.11.0] — 2026-11-09

Английская локализация интерфейса и переключатель языка (T-153).

### Добавлено

- **T-153.1 — i18n-слой.** `react-i18next` + `i18next`; словари
  `frontend/src/locales/ru.json` и `en.json`; `frontend/src/i18n.ts`
  инициализирует русский язык по умолчанию и английский как fallback.
  Выбранный язык хранится в `localStorage` (`vetassistant.language`).
- **T-153.2 — перевод UI.** Все захардкоженные строки вынесены в словари:
  чат (`App`, `Welcome`, `Composer`, `MessageBubble`, `ToolCallBadge`),
  авторизация и заявка на доступ, сайдбар, настройки, смена пароля,
  Telegram-привязка, админ-панель (заявки, пользователи, аналитика).
  Строки ошибок API и экспорта истории также локализуются.
- **T-153.3 — переключатель RU/EN.** Кнопки в сайдбаре, на экране входа и в
  настройках; язык меняется мгновенно без перезагрузки, обновляются
  `document.documentElement.lang`, заголовок вкладки и meta-description.
- **T-153.4 — даты и числа через `Intl`.** Даты приёмов, регистрации и
  привязки Telegram форматируются `Intl.DateTimeFormat` с учётом языка;
  KPI-числа и проценты в аналитике используют локальные разделители и
  сокращения («12,3 тыс.» / «12.3K»).

### Изменено

- Версия `1.11.0` в `pyproject.toml`, `app/main.py`, `frontend/package.json`,
  `frontend/package-lock.json`, README.
- `README.md`: раздел v1.11.0 и статус; `TODO.md`: T-153 закрыта.

### Проверено

- Frontend: `npm run lint` (0 ошибок), `npm test`, `npm run build` — успешно.
- Python: `pytest`, `ruff check .`, `mypy app` — чисто.

## [1.10.0] — 2026-11-09

Экспорт оценок для DPO/SFT (T-150) и активность пользователей в админке
(T-151).

### Добавлено

- **T-150 — экспорт оценок.** `scripts/export_feedback.py` выгружает таблицу
  `feedback` в JSONL: по одной записи на строку с полями `message_id`,
  `rating`, `created_at`. Текстов диалогов в выгрузке нет (152-ФЗ). Фильтры
  `--since`/`--until` (дата `YYYY-MM-DD` или ISO-datetime UTC; `--until`
  датой включает день целиком), `--rating 1|-1`, `--limit`. По умолчанию —
  stdout (только JSONL, служебные сообщения в stderr), с `--output FILE` —
  файл. `--include-user-id` добавляет псевдоним пользователя
  (HMAC-SHA256, соль из `VET_EXPORT_PSEUDONYM_SALT`); без соли скрипт
  завершается с кодом 2, чтобы псевдонимы нельзя было обратить. Коды выхода
  0/1/2, документация в `DEPLOYMENT.md` §8.
- **T-151 — активность DAU/WAU.** `GET /v1/admin/activity?window=7d|30d`
  (только админ): DAU для каждого дня окна и WAU (уникальные пользователи
  за 7 дней) по метрике Prometheus `vet_llm_user_requests_total`; в ряду
  также число вызовов модели за день. Graceful fallback: если Prometheus
  не задан или недоступен, API отвечает `200` с `source="unavailable"`,
  пустым рядом и `degraded`, отражающим причину.
- **Админка.** В `AdminAnalytics` — панель «Активность пользователей»:
  переключатель 7/30 дней, карточки DAU/WAU и график активных пользователей
  по дням; отдельные состояния загрузки/ошибки, чтобы сбой активности не
  ломал остальную аналитику. Кнопка «Обновить» обновляет и метрики, и
  активность; данные автообновляются раз в минуту.
- **Тесты.** `tests/test_export_feedback.py` — 21 тест: фильтры периода/
  оценки/лимита, запись в файл, псевдонимизация и обязательная соль,
  отсутствие текстов в выгрузке, коды выхода. `tests/test_admin_activity.py` —
  8 тестов: права доступа, fallback без Prometheus и при недоступном
  Prometheus, расчёт DAU/WAU, параметры range-запроса (шаг — сутки, окна
  7d/30d). Frontend: тесты `fetchAdminActivity`.

### Изменено

- Версия `1.10.0` в `pyproject.toml`, `app/main.py`, `frontend/package.json`,
  `frontend/package-lock.json`, README.
- `README.md`: раздел v1.10.0 и статус; `DEPLOYMENT.md`: экспорт оценок,
  эндпоинт активности и примеры версии; `TODO.md`: T-150 и T-151 закрыты,
  T-152/T-153 остаются кандидатами.

### Проверено

- `pytest`: 814 тестов; `ruff check .` и `mypy app` — чисто.
- Frontend: `npm run lint` (0 ошибок), `npm test` — 79 тестов,
  `npm run build` — успешно.

## [1.9.0] — 2026-11-09

Обратная связь по ответам 👍/👎 (T-139): одна оценка на сообщение, KPI в
админке; тексты диалогов в БД не хранятся (152-ФЗ).

### Добавлено

- **T-139.1 — схема `feedback`.** Модель `Feedback` в `app/database.py`:
  `user_id` (FK `users.id ON DELETE CASCADE`, индекс), `message_id`
  `VARCHAR(128)` (индекс, непрозрачный id сообщения на клиенте), `rating`
  `SMALLINT CHECK (rating IN (1, -1))`, `created_at`;
  `UNIQUE (user_id, message_id)`. Идемпотентная миграция для прода —
  `scripts/migrations/2026-11-09_feedback.sql` (таблица, индексы, ограничения,
  откат). Текстов диалогов в таблице нет — восстановить переписку нельзя.
- **T-139.2 — API.** `POST /v1/feedback` (JWT) принимает `{message_id,
  rating}` и делает upsert: повторная оценка перезаписывает прежнюю, дублей
  нет. `GET /v1/admin/feedback/stats` (только админ) отдаёт `total`,
  `positive`, `negative`, `positive_ratio`. При удалении аккаунта оценки
  удаляются каскадом.
- **T-139.3 — frontend.** Кнопки 👍/👎 под завершёнными ответами ассистента
  (`MessageBubble`): выбранная оценка подсвечивается, `aria-pressed` и
  русские подписи, кнопки блокируются на время запроса. Оценка отправляется
  на `POST /api/v1/feedback`; ошибка показывается неблокирующим баннером и не
  сбрасывает прошлую оценку.
- **T-139.4 — админка.** На вкладке «Аналитика» — KPI-карточка «Рейтинг
  ответов» (доля 👍, число оценок, расклад 👍/👎); сбой загрузки статистики
  не ломает остальные метрики.
- **Тесты.** `tests/test_feedback.py`: 401/403, валидация `rating` и
  `message_id`, upsert, изоляция пользователей, сводка и доля, каскад при
  удалении, ограничения БД, наличие миграции, отсутствие колонок с текстом.
  Frontend: тесты `submitFeedback`/`fetchFeedbackStats`.

### Изменено

- Версия `1.9.0` в `pyproject.toml`, `app/main.py`, `frontend/package.json`,
  `frontend/package-lock.json`, README.
- `README.md`: раздел v1.9.0 и статус; `DEPLOYMENT.md`: миграция `feedback`
  и примеры версии; `TODO.md`: T-138 закрыта, T-139.1–T-139.5 выполнены.
- `app/database.py::delete_user_account`: удаляет оценки пользователя.

### Проверено

- `pytest`: 785 тестов; `ruff check .` и `mypy app` — чисто.
- Frontend: `npm run lint` (0 ошибок), `npm test` — 77 тестов,
  `npm run build` — успешно.

## [1.8.2] — 2026-11-09

Патч GPU-стрима: `usage` снова приходит от LM Studio (T-138.5).

### Исправлено

- **T-138.5 — `usage` в GPU-стриме.** `GpuHttpBackend.stream_chat_completion`
  не передавал в LM Studio `stream_options: {"include_usage": true}`, поэтому
  OpenAI-совместимый сервер (как и сам OpenAI) не присылал `usage` в SSE.
  Теперь параметр добавляется в payload через `setdefault` перед запросом;
  явное значение от вызывающего кода сохраняется. `usage` последнего чанка
  снова попадает в финальный SSE-чанк API, метрики `vet_llm_*` и админскую
  аналитику. CPU-путь не менялся.
- **Тест.** Проверка, что стриминговый запрос GPU-бэкенда содержит
  `stream_options.include_usage`.

### Изменено

- Версия `1.8.2` в `pyproject.toml`, `app/main.py`, `frontend/package.json`,
  `frontend/package-lock.json`, README.
- `README.md`: раздел v1.8.2 и статус; `DEPLOYMENT.md`: примеры версии.
- `TODO.md`: T-138.5 закрыта.

### Проверено

- `pytest`: 770 тестов; `ruff check .` и `mypy app` — чисто.

## [1.8.1] — 2026-11-09

Точный `usage` в стриминге (T-138): токены CPU-модели считаются в API,
`usage` GPU-бэкенда пробрасывается, SSE заканчивается usage-чанком.

### Добавлено

- **T-138 — usage в потоковых ответах.** `app/inference_usage.py`:
  `StreamUsageTracker` считает prompt по `Llama.n_tokens` после префилла,
  completion — по `Llama.tokenize` сгенерированного текста; при отсутствии
  `n_tokens`/tokenizer используется лексический fallback. Для GPU-бэкенда
  (LM Studio) `usage` из последнего SSE-чанка имеет приоритет и передаётся
  дальше.
- **Финальный usage-чанк.** SSE-поток заканчивается чанком
  `{"usage": {"prompt_tokens": X, "completion_tokens": Y, "total_tokens": Z}}`
  с пустым `choices`; в ветке с инструментами usage добавлен в финальный
  stop-чанк.
- **Тесты.** API-тест проверяет ненулевой usage в конце стрима; отдельный
  тест — рост `vet_llm_prompt_tokens_total` / `completion_tokens_total`;
  тест CPU-бэкенда — расчёт по `n_tokens` и tokenizer.

### Изменено

- Версия `1.8.1` в `pyproject.toml`, `app/main.py`, `frontend/package.json`,
  `frontend/package-lock.json`, README.
- `README.md`: раздел v1.8.1 и статус; `DEPLOYMENT.md`: примеры версии.
- `TODO.md`: T-138.1–T-138.2 закрыты; сверка на 20 промптах и проверка
  Grafana остаются после релиза.

### Проверено

- `pytest`: 769 тестов; `ruff check .` и `mypy app` — чисто.
- Frontend: `npm test` — 74 теста (изменений в UI не было).

## [1.8.0] — 2026-11-08

Управление пользователями в админ-панели (T-140): блокировка действует
мгновенно, удаление аккаунта каскадное, все действия пишутся в аудит.

### Добавлено

- **T-140.1 — схема и миграция.** `users.is_active BOOLEAN NOT NULL
  DEFAULT TRUE`, таблица `admin_actions` (`admin_id`, `target_user_id`,
  `action`, `reason`, `created_at`, CHECK `block/unblock/delete`).
  Идемпотентная миграция в `Database.create_tables()` и SQL для прода
  `scripts/migrations/2026-11-08_user_management.sql`.
- **T-140.2 — API модерации.** `GET /v1/admin/users` — поиск по email,
  фильтр `all/active/blocked`, пагинация, без `hashed_password`;
  `POST /v1/admin/users/{id}/block` и `/unblock` — с причиной и записью в
  `admin_actions`; `DELETE /v1/admin/users/{id}` — подтверждение по email,
  каскад `appointments`/`reminders`/`telegram_link_codes`, обнуление
  `access_requests.reviewed_by/approved_user_id`.
- **T-140.3 — блокировка JWT и входа.** `get_current_user` возвращает 403
  заблокированному, `POST /v1/auth/login` — 403 «Аккаунт заблокирован.
  Обратитесь к администратору»; неверный пароль остаётся 401.
- **T-140.4 — UI.** Третья вкладка «Пользователи» в `AdminDashboard`:
  поиск, фильтр, пагинация, статусы, block/unblock с причиной, удаление с
  подтверждением email.
- **Защита.** Нельзя заблокировать/удалить себя и последнего активного
  администратора; повторные block/unblock идемпотентны; журнал не хранит
  пароли и токены.

### Изменено

- Версия `1.8.0` в `pyproject.toml`, `app/main.py`, `frontend/package.json`,
  `frontend/package-lock.json`, README.
- `DEPLOYMENT.md` §8: миграция T-140, проверка и откат.
- `TODO.md`: T-140 и подзадачи закрыты; T-138 перенесена на следующий релиз.

### Эксплуатация

- Перед деплоем v1.8.0 применить SQL к прод-БД:

  ```bash
  cd /srv/vetassistant
  docker compose -f docker-compose.edge.yml exec -T db \
    sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' \
    < scripts/migrations/2026-11-08_user_management.sql
  ```

- Новый API докатывает схему при старте (`create_all` + `ALTER TABLE`), но
  SQL даёт управляемый деплой и заранее подготовленную схему.
- Откат схемы — только после откачки API на предыдущую версию:
  `DROP TABLE admin_actions`, затем `DROP COLUMN users.is_active`.

### Проверено

- `pytest`: 765 тестов; `ruff check .` и `mypy app` — чисто.
- Frontend: `npm run lint`, `npm test` (74 теста), `npm run build` — зелёные.
- CI v1.8.0 — прогон на релизном коммите: Lint & Test, Frontend, Docker
  Build.

### Примечание

- T-138 (точные токены и `usage` в стриминге) в этот релиз не входит и
  остаётся следующей задачей.

## [1.7.1] — 2026-11-08

Патч прямого запуска скриптов оценки RAG (T-147).

### Исправлено

- **T-147 — `ModuleNotFoundError` при прямом запуске скриптов.** Запуск
  `python scripts/evaluate_hybrid_rag.py` и `python scripts/evaluate_rag.py`
  падал внутри контейнера: при прямой форме в `sys.path[0]` попадал только
  каталог `scripts/`, а импорт `from scripts.evaluate_rag import ...` требовал
  корень репозитория. Оба скрипта теперь сами добавляют корень репозитория в
  `sys.path`, поэтому работают и `python scripts/...`, и
  `python -m scripts....` — из `/srv/vetassistant` и из `/app` в контейнере.

### Изменено

- `DEPLOYMENT.md` §6.7: описаны обе формы запуска скриптов.
- `TODO.md`: T-147 закрыт; добавлен план Фазы 7 (v1.8.0).

### Проверено

- `pytest`: 753 теста зелёные; `ruff check .` и `mypy app` — чисто.
- `--dry-run` проходит обоими способами для `evaluate_hybrid_rag.py` и
  `evaluate_rag.py`.

## [1.7.0] — 2026-11-08

Hybrid Search в RAG (T-141): качество поиска по базе знаний без новой
инфраструктуры и без пересборки production-образа ради дополнительных
зависимостей. На реальном индексе гибрид поднял Hit@3 с **70.6 % до 100 %**.

### Добавлено

- **T-141 — гибридный поиск BM25 + векторы.** `app/rag_hybrid.py` содержит
  собственную реализацию Okapi BM25 (`k1=1.5`, `b=0.75`), токенизацию
  `[а-яёa-z0-9]+` с лёгким снятием английского множественного `-s` и слияние
  ранжирований Reciprocal Rank Fusion (`k=60`). Внешняя зависимость
  `rank-bm25` не добавлялась: BM25 работает на чистом Python, образ не
  пересобирается, тесты не требуют сети.
- **Гибридный режим `ChromaKnowledgeBase`.** Векторный top-10 и BM25 top-10
  по одним и тем же чанкам сливаются через RRF, из результата берутся
  `top_k=3`. BM25 строится в памяти при старте API; при ошибке построения
  или поиска база прозрачно деградирует до `vector` с предупреждением в лог.
  `vector` остаётся полностью доступен флагом `VET_API_RAG_MODE=vector`.
- **Русско-английский глоссарий запроса.** Статьи MSD Vet Manual
  англоязычные, а вопросы — русские, поэтому «чистый» BM25 по русскому
  запросу не находит нужную статью. Глоссарий `RU_EN_TERMS` (~110 основ)
  переводит значимые термины: «ксилитом» → `xylitol`, «фомепизол» →
  `fomepizole`, «фенобарбитал» → `phenobarbital`, «ацетилцистеин» →
  `acetylcysteine`, «ивермектин» → `ivermectin`. Совпадение — по префиксу с
  окончанием до трёх символов; короткие ключи сравниваются точно. Если
  перевод найден, вес русских токенов понижается до `0.25`, чтобы профильные
  английские статьи выигрывали у маленьких русских демо-файлов.
- **Заголовок чанка в metadata.** `scripts/ingest_knowledge.py` пишет
  `title` (строка `Title:` у статей MSD, иначе первая содержательная строка).
  BM25 повторяет токены заголовка с весом `2`, поэтому статья находится по
  названию болезни или токсина. Повторный ingest через `upsert` обновляет
  metadata существующих чанков; `--rebuild` не обязателен.
- **Замер hit rate поиска.** `scripts/evaluate_hybrid_rag.py` проверяет не
  ответ модели, а сам поиск: попала ли ожидаемая статья в top_k. Режимы
  `bm25` (офлайн, без ChromaDB), `vector`, `hybrid`, `both` (на сервере);
  метрики — hit rate@k, MRR, среднее и p95 времени поиска. 17 вопросов:
  12 из T-133 и 5 новых с точными названиями препаратов.
- **Настройки:** `VET_API_RAG_MODE=vector|hybrid` (по умолчанию `hybrid`),
  `VET_API_RAG_CANDIDATES=10`, `VET_API_RAG_BM25_WEIGHT=1.0`. Прокинуты в
  `docker-compose.yml`, `docker-compose.prod.yml`, `docker-compose.edge.yml`,
  `.env.example` и `.env.production.example`.

### Результаты офлайн-замера (BM25, 766 чанков)

| Режим | Hit@3 | Hit rate | MRR | p95 поиска |
|---|---:|---:|---:|---:|
| BM25 без глоссария | 0/17 | **0 %** | 0.000 | 1.2 мс |
| BM25 + глоссарий + вес RU 0.25 | **17/17** | **100 %** | **0.931** | **3.6 мс** |

Все пять препаратных вопросов (фомепизол, ацетилцистеин, ивермектин,
фенобарбитал, леветирацетам) попали в нужную статью с первого чанка.
Бюджет p95 «не больше 100 мс» не расходуется. Это замер лексического канала;
сравнение с vector-only на реальном индексе — ниже.

### Результаты серверного замера (ChromaDB, 17 вопросов)

Прогон `scripts/evaluate_hybrid_rag.py --mode both` на production-индексе,
2026-11-08:

| Режим | Hit@3 | Hit rate | MRR | p95 |
|---|---:|---:|---:|---:|
| vector | 12/17 | 70.6 % | 0.676 | 54.5 мс |
| **hybrid** | **17/17** | **100 %** | **0.912** | **140.3 мс** |

Гибрид закрыл все пять провалов vector-only: статьи про препараты, которые
эмбеддинги «размывали», теперь находятся BM25-каналом. Прирост p95 —
+85.8 мс, в пределах бюджета +100 мс. По итогам замера утверждён
`VET_API_RAG_BM25_WEIGHT=1.0`; полный откат — `VET_API_RAG_MODE=vector`.

### Исправлено

- **T-146 — зависание CI на `setup-python`.** Шаг `actions/setup-python@v5`
  с `cache: pip` синхронизировал кэш с GitHub Cache Service и в российских
  сетях зависал на 18+ минут, блокируя релиз. Параметры `cache: pip` и
  `cache-dependency-path` убраны: на self-hosted раннере pip-кэш хранится
  локально и переживает прогоны. Job `lint-and-test` ограничен
  `timeout-minutes: 20`, чтобы зависший job убивался автоматически.

### Изменено

- `scripts/ingest_knowledge.py`: metadata чанка теперь `{source, title}`.
- `README.md`: раздел «Гибридный поиск: BM25 + векторы» — режимы, глоссарий,
  команды замера; обновлён состав базы (17 статей MSD).
- `DEPLOYMENT.md`: пересборка индекса, обязательный рестарт API после
  ingest, настройки режима и откат на `vector`.
- `docs/development/reports/RAG_EVAL.md`: §8 — методика, офлайн- и серверный
  замеры, критерии приёмки.
- `DEPLOYMENT.md`: §6.7 «Запуск новых скриптов до релиза» — монтирование
  репозитория в контейнер, пока образ ещё не содержит новых скриптов.
- `TODO.md`: T-141 и подзадачи T-141.1–T-141.9 закрыты.

### Эксплуатация

- После `scripts/ingest_knowledge.py` API нужно перезапустить: BM25 строится
  при старте и не видит чанки, добавленные позже.
- Если hybrid ухудшит hit rate относительно vector-only, вес BM25 понижается
  до `0.5`, затем `0.3`; полный откат — `VET_API_RAG_MODE=vector`. Обе
  настройки применяются рестартом api.
- Замер без генерации ответов и без риска OOM — отдельным контейнером:
  `docker compose -f docker-compose.edge.yml run --rm --no-deps --entrypoint
  python api scripts/evaluate_hybrid_rag.py --mode both`. На образе до v1.7.0
  скрипта в контейнере нет — используйте монтирование репозитория
  (`DEPLOYMENT.md` §6.7).

### Проверено

- `pytest`: 752 теста зелёные; `ruff check .` и `mypy app` — чисто.
- Офлайн-замер: 17/17 hit@3 с глоссарием против 0/17 без него; артефакты
  `data/rag_hybrid_eval_bm25.json` и `data/rag_hybrid_eval_bm25_plain.json`.
- Серверный замер: hybrid **17/17 (100 %)** против vector **12/17 (70.6 %)**;
  MRR 0.912 против 0.676; p95 140.3 мс против 54.5 мс. Вес BM25 утверждён
  равным `1.0`.
- CI v1.7.0 на коммите `a4fc3d3` — зелёный: Frontend, Docker Build и
  Lint & Test (Ruff, Mypy, 752 pytest) без зависаний после фикса T-146.

## [1.6.1] — 2026-11-06

Hotfix T-143 по итогам аудита падений и глюков + GPU-диспетчер T-144.

### Добавлено

- **T-144 — GPU-бэкенд с fallback на CPU.** `app/backends.py` содержит
  протокол `InferenceBackend`, `GpuHttpBackend` (LM Studio по
  OpenAI-протоколу через обратный SSH-туннель) и `CpuLlamaBackend` (текущий
  llama.cpp с общим локом T-143). `BackendRouter` в `app/router.py` делает
  probe раз в 15 секунд, держит circuit breaker (3 ошибки → cooldown 180 с)
  и переключает запросы на CPU; стрим падает обратно на CPU только до первого
  чанка, чтобы не дублировать текст. `/health` показывает `backend: gpu|cpu`,
  добавлены метрики `vet_llm_backend_requests_total{backend,status}` и
  `vet_llm_backend_ttft_seconds`.
  Настройки: `VET_API_GPU_BACKEND_ENABLED`, `VET_API_GPU_BACKEND_BASE`,
  `VET_API_GPU_BACKEND_API_KEY`, `VET_API_GPU_BACKEND_MODEL`,
  `VET_API_GPU_BACKEND_PROBE_INTERVAL_S`, `VET_API_GPU_BACKEND_PROBE_TIMEOUT_S`,
  `VET_API_GPU_BACKEND_TTFT_FALLBACK_S`.

### Исправлено

- **H-1 — segfault при параллельных запросах.** Все вызовы
  `llama-cpp-python` (`create_chat_completion`, включая стриминг) обёрнуты в
  общий `threading.Lock`. Стрим удерживает лок на всё время генерации, но
  генерируется в отдельном потоке и отдаётся в event loop через очередь,
  поэтому параллельные запросы больше не ломают llama.cpp и не блокируют
  сервер.
- **H-4 — `<think>` в ответах Qwen3.** Reasoning-блоки вырезаются из
  нестриминговых ответов, ответов агента и SSE-потока. Потоковый фильтр
  корректно переживает тег, разрезанный между чанками, и отбрасывает
  незакрытый reasoning в конце генерации.
- **H-3 — устаревшая дата в ответах.** В системный промпт добавлена строка
  `Сегодня: YYYY-MM-DD. Завтра: YYYY-MM-DD.`, рассчитанная на момент запроса.
- **H-2 — повторный `/link`.** Ответ API 403 (бот после привязки входит уже
  под JWT веб-владельца) теперь показывается пользователю как «Этот аккаунт
  уже привязан. Используйте /unlink, чтобы отвязать».
- **H-5 — дубли уведомлений.** Уведомления API → Telegram отправляются только
  после `book_appointment`; `set_reminder` больше не спамит в чат.
- **T-145 — осиротевший контейнер при деплое.** После прошлых релизов на
  сервере оставался контейнер `60577ee94155_vetassistant-api`, который держал
  имя `vetassistant-api` и мешал пересозданию сервиса. В
  `.github/workflows/deploy.yml` (шаг «Pull and rebuild on server») и в
  `scripts/restart_prod.sh` добавлен `docker compose up -d --no-build
  --remove-orphans`: удаляются только контейнеры текущего compose-проекта,
  которых нет в актуальном compose-файле. Caddy, Prometheus и Grafana живут
  в других проектах и не затрагиваются; сборка образов и фиксация
  `VETASSISTANT_VERSION` не изменились.

### Приёмочные испытания v1.6.1

Тест-матрица пройдена на production edge-стеке 2026-11-06:

| Проверка | Результат |
|---|---|
| H-1, стресс-тест параллельных запросов | пройден: нет `exit 139`, `RestartCount=0` |
| GPU → CPU → GPU fallback | переключение в обе стороны без рестарта API |
| E2E Function Calling на GPU | **3.4 с** вместо **75 с** на CPU (≈**20×**) |
| Дата в ответе | `2026-11-07` — верная |
| `<think>` в ответах | не просачивается ни в текст, ни в стрим |
| Telegram-уведомления | пришли только для `book_appointment` |

### Изменено

- Версия `1.6.1` в `pyproject.toml`, FastAPI, `frontend/package.json`,
  `frontend/package-lock.json` и README.

## [1.6.0] — 2026-11-05

### Добавлено

- **Привязка Telegram к веб-аккаунту (T-134).** Пользователь создаёт
  одноразовый код в настройках сайта и отправляет боту `/link КОД`; после
  подтверждения бот работает от имени веб-пользователя, а записи,
  напоминания и уведомления становятся общими с сайтом.
  - Схема: `users.telegram_id` (`BIGINT`, UNIQUE) и таблица
    `telegram_link_codes` (только HMAC-SHA256 от кода, `expires_at`,
    `used_at`). Мягкая миграция в `create_tables` и идемпотентный SQL
    `scripts/migrations/2026-11-05_telegram_linking.sql` для прода.
  - API: `POST /v1/telegram/link-code`, `POST /v1/telegram/confirm`,
    `POST /v1/telegram/unlink`, `GET /v1/telegram/link`,
    `DELETE /v1/telegram/link`. Код живёт 10 минут, одноразовый, не более
    трёх активных, 5 запросов в час; чужой synthetic-JWT → 403, занятый
    `telegram_id` → 409.
  - Бот: команды `/link КОД`, `/unlink`, `/status`; логин synthetic-аккаунтом
    возвращает JWT привязанного веб-пользователя (synthetic-аккаунт
    сохраняется как техническая identity бота).
  - **Уведомления API → Telegram (T-134.4):** после успешных
    `book_appointment`/`set_reminder` привязанному пользователю уходит
    сообщение в чат (таймаут 5 с, ошибки только в лог). Запросы бота
    помечаются `X-Vet-Client` и не дублируются.
  - **Frontend:** в настройках появился блок «Telegram» — статус, привязка,
    код с обратным отсчётом и копированием, отвязка с подтверждением.
  - `scripts/migrate_telegram_link.py`: отчёт по synthetic-аккаунтам,
    перенос старых `appointments`/`reminders` на веб-аккаунт и привязка
    `telegram_id` (`--merge-user ... --dry-run`). Synthetic-аккаунт не
    удаляется — иначе бот не сможет войти.
- Настройки API `VET_API_TELEGRAM_NOTIFY`, `VET_API_TELEGRAM_API_BASE`,
  `VET_API_TELEGRAM_BOT_USERNAME`; `TELEGRAM_BOT_TOKEN` теперь передаётся и
  сервису `api` (для `sendMessage`).

### Изменено

- Версия `1.6.0` в `pyproject.toml`, FastAPI, `frontend/package.json`,
  `frontend/package-lock.json` и README.
- `DEPLOYMENT.md`: раздел «Миграция Telegram-привязки (T-134)» — SQL,
  проверка схемы, переменные, команды бота, перенос данных и откат.
- README: описание привязки, команды бота и переменные уведомлений.

### Безопасность

- В БД хранится только HMAC-SHA256 кода; сам код не логируется. Проверка
  synthetic-email `telegram-<id>@bot.vetassistant.local` не даёт подтвердить
  привязку за чужой Telegram; конфликт `telegram_id` не сливает аккаунты
  автоматически.

## [1.5.6] — 2026-11-05

### Добавлено

- **Аналитика в админ-панели (T-135).** В `AdminDashboard` появилась вкладка
  «Аналитика»: KPI-карточки (запросы, токены, RAG hit rate, ошибки 5xx),
  графики запросов и токенов по времени, таблица топ-5 пользователей с числом
  запросов и потраченных токенов, переключатель 24 ч / 7 д и автообновление
  раз в минуту. Список заявок и его approve/reject-флоу не изменились.
- **`GET /v1/admin/metrics`** — агрегаты под `get_current_admin`: источник
  `prometheus` (история за окно) или `in_process` (снимок с момента запуска
  API), флаг `degraded` и `started_at`. Запросы к Prometheus — фиксированный
  allowlist, клиент выбирает только окно.
- **Метрики по пользователям:** `vet_llm_user_requests_total{user_id}` и
  `vet_llm_user_tokens_total{user_id,kind}` — основа для топа пользователей.
- Настройки `VET_API_PROMETHEUS_URL` (по умолчанию `http://vetassistant-prometheus:9090`)
  и `VET_API_PROMETHEUS_TIMEOUT_S` (2 секунды).
- SVG-график `Sparkline` и хелперы `frontend/src/lib/metrics.ts` — без новых
  зависимостей.
- **`--reset-password` в `scripts/create_telegram_user.py`.** После ротации
  `VET_BOT_AUTH_SECRET` существующему synthetic-пользователю перезаписывается
  bcrypt-хэш по новому секрету; без флага скрипт, как и раньше, сообщает
  «уже существует» и ничего не меняет.

### Изменено

- **RAG:** `scripts/download_msd.py` принимает `--url` и скачивает статьи по
  прямым ссылкам (имя файла выводится из URL), `scripts/ingest_knowledge.py`
  пишет «новых / обновлено / всего в коллекции». Индекс расширен до
  766 чанков (+562 к v1.5.5), upsert сохраняет прежние чанки.
- `DEPLOYMENT.md`: раздел «Как добавить новые статьи в RAG» и описание
  админской аналитики (Prometheus против in-process); уточнено, что `data/`
  смонтирован bind-mount — статьи видны в контейнере сразу после `git pull`,
  но ingest нужно запускать вручную.
- Версия `1.5.6` в `pyproject.toml`, FastAPI, `frontend/package.json`,
  `frontend/package-lock.json` и README.
- **Prometheus:** адрес по умолчанию — `http://vetassistant-prometheus:9090`
  (настройки, `.env.example`, edge-compose); в prod-compose переменная пустая,
  чтобы не ждать таймаут там, где Prometheus не развёрнут.
- **Деплой:** шаг `Persist image version to .env` стал best-effort — чужой
  `.env` (root-only) больше не валит релиз, в лог уходит warning с командой
  `sudo chown`; добавлен `workflow_dispatch` с параметром `version` для
  повторного деплоя без нового тега.

### Исправлено

- Админка не зависит от Grafana: при недоступном Prometheus эндпоинт отдаёт
  локальный снимок с `degraded: true` вместо ошибки, а графики честно
  показывают «история недоступна без Prometheus».

## [1.5.5] — 2026-11-04

### Добавлено

- **Динамические версии Docker-образов (T-131).** `docker-compose.edge.yml` и
  `docker-compose.prod.yml` (а также dev-файл) больше не содержат
  захардкоженного тега: `image: vetassistant:${VETASSISTANT_VERSION:-latest}` и
  `vetassistant-frontend:${VETASSISTANT_VERSION:-latest}`. В `deploy.yml`
  добавлен шаг `Resolve image version from tag`, который превращает тег
  `v1.5.5` в `1.5.5` и передаёт значение в `docker compose` через `env`.
  Теперь `docker ps` показывает реально запущенную сборку, а не застывший
  `1.5.3`.
- Раздел README «Версии Docker-образов и процесс релиза»: как тег попадает в
  имя образа, как проверить версию через `docker compose ps` и
  `/api/openapi.json`, почему тег ставится после зелёного CI.

### Изменено

- **Ускорение CI/CD (T-130).** Тег `v1.5.5` прошёл пайплайн за ~14 минут:
  `Release` — 17 секунд (было 40 минут, пока в нём собирались образы),
  `Deploy` — 13м48с вместо 74м28с. На `v1.5.4` тег ждал 35 минут в очереди
  за CI, теперь ожидания нет.
- Порядок релиза: тег ставится **после** зелёного CI на `main`
  (`DEPLOYMENT.md`, раздел 6.5), поэтому теговые workflow больше не стоят в
  очереди за CI.
- Версия `1.5.5` в `pyproject.toml`, FastAPI, `frontend/package.json`,
  `frontend/package-lock.json`, README и Docker Compose.

### Исправлено

- Захардкоженный тег `vetassistant:1.5.3` в compose-файлах: на проде после
  хотфикса работала сборка `1.5.3`, хотя тег был `v1.5.4`, и по `docker ps`
  нельзя было понять, какая версия развёрнута.

## [1.5.3] — 2026-11-04

### Добавлено

- **Telegram API через reverse-proxy (Cloudflare Worker).** Переменная
  `VET_BOT_TELEGRAM_API_BASE` (по умолчанию `https://api.telegram.org`)
  позволяет направить Bot API на Worker, если прямой доступ к
  `api.telegram.org` с VPS заблокирован. `bot/main.py` создаёт
  `AiohttpSession(api=TelegramAPIServer.from_base(...))`; переменная передаётся
  в контейнер `bot` через `docker-compose.edge.yml`.
- `scripts/create_telegram_user.py` — создание Telegram-пользователя одной
  командой: скрипт сам вычисляет synthetic email и пароль из
  `VET_BOT_AUTH_SECRET` (fallback — `TELEGRAM_BOT_TOKEN`) и не печатает пароль.
- Тесты `create_bot` с `http://mock` — без обращений к реальному Telegram.

### Изменено

- **CI/CD (T-130).** Из `release.yml` удалена сборка Docker-образов `api` и
  `frontend`: тег `v*` больше не собирает образы дважды, сборка осталась
  только в `deploy.yml`, а `release.yml` создаёт исключительно GitHub Release.
  Job `build-and-release` переименован в `create-release` с таймаутом 10 минут.
- Версия `1.5.3` в `pyproject.toml`, FastAPI, Docker Compose (dev/prod/edge)
  и `frontend/package.json`.

### Исправлено

- **Авторизация синтетических email Telegram-пользователей (хотфикс
  `425933e`).** `LoginRequest.email` больше не `EmailStr`: для входа достаточно
  строки, поэтому адреса вида `telegram-<id>@bot.vetassistant.local` с
  зарезервированным доменом `.local` принимаются, и бот снова отвечает на
  вопросы в Telegram, в том числе через RAG. Регрессионный тест — в
  `tests/test_api.py`.
- **Гонки в CI/CD.** Деплой сериализован через
  `concurrency: deploy-production` (второй запуск ждёт первый); `deploy.yml`
  собирает `api` и `frontend` по отдельности, иначе параллельный `docker build`
  падал с `image already exists`; стек поднимается через `up -d --no-build`,
  чтобы контейнеры не стартовали на старом образе.

## [1.5.2] — 2026-11-04

### Исправлено

- Fixed Docker image race condition in deploy workflow: `api` и `bot`
  используют один image tag, поэтому параллельная сборка падала с
  `image already exists`. Деплой собирает только `api` и `frontend`
  (`docker compose build api frontend`), затем поднимает стек через
  `up -d --no-build`.
- Убрана гонка между `build` и `up`, из-за которой контейнеры могли
  запуститься на старом образе.

### Изменено

- Optimized CI for self-hosted runner: `apt-get` выполняется только на
  GitHub-hosted runner (`runner.environment == 'github-hosted'`), на VPS
  используются уже установленные зависимости.
- Версия `1.5.2` в `pyproject.toml`, FastAPI, Docker Compose (dev/prod/edge)
  и `frontend/package.json`.

## [1.5.1] — 2026-11-04

### Исправлено

- Admin UI: результат `GET /v1/auth/me` теперь применяется к текущей сессии
  и сохраняется в `localStorage`. У пользователей со старой сессией (созданной
  до появления `is_admin`) вкладка «Администрирование» появляется без
  повторного логина; Sidebar получает актуальный `is_admin`.

### Изменено

- CI/CD переведён на **self-hosted runner** на VPS: все workflow используют
  `runs-on: [self-hosted, linux, x64, vps]`.
- `deploy.yml` больше не использует `appleboy/ssh-action` и SSH-секреты:
  деплой выполняется обычным bash-шагом на сервере
  (`cd /srv/vetassistant && git pull --ff-only && docker compose … up -d --build`).
- Версия `1.5.1` в `pyproject.toml`, FastAPI, Docker Compose (dev/prod/edge)
  и `frontend/package.json`.

### Документация

- `docs/GITFLIC_ONBOARDING.md` и `docs/build_gitflic_onboarding_docx.py` —
  руководство по переезду на GitFlic и сборке DOCX-версии.
- `DEPLOYMENT.md`: установка и проверка self-hosted runner, метки, отказ от
  SSH-секретов.

## [1.5.0] — 2026-11-04

### Добавлено

#### Экспорт истории диалога (T-123)

- Кнопка **«Скачать историю»** в сайдбаре: Markdown-файл с ролями, текстом,
  вызовами инструментов и датами сообщений; скачивание через `Blob` и
  `URL.createObjectURL`, без отправки данных на сервер.
- `createdAt` в сообщениях и в `localStorage`; старые сообщения без даты не
  ломают экспорт; кнопка недоступна при пустой истории.

#### Telegram-бот в production (T-121)

- Сервис `bot` в `docker-compose.edge.yml`: `python -m bot`, без публикации
  портов, `VET_BOT_API_URL=http://api:8000/v1/chat/completions`,
  `VET_BOT_USE_RAG=true`, зависимость от здорового `api`.
- Закрытый доступ: allowlist `VET_BOT_ALLOWED_TELEGRAM_IDS` (ID через
  запятую). ID вне списка получает сообщение «Доступ к боту ограничен…»;
  бот не вызывает API и не создаёт аккаунт. Пустой allowlist — контейнер
  завершается с ошибкой (fail closed).
- Бот больше **не регистрирует** пользователей: аккаунт
  `telegram-<id>@bot.vetassistant.local` создаёт администратор после
  одобрения заявки.

#### Расширение RAG (T-124)

- Добавлены 5 статей MSD Vet Manual: токсичность шоколада, блохи, клещи
  (кошки и собаки), вакцинация; коллекция `msd_vet_manual` выросла до
  **204 чанков**.
- Тексты лежат в Git (`data/knowledge/real/`), индекс обновляется
  `scripts/ingest_knowledge.py` через `upsert` без удаления старых чанков.

### Исправлено

- Admin UI: результат `GET /v1/auth/me` теперь применяется к текущей сессии и
  сохраняется в `localStorage`. У пользователей со старой сессией (созданной до
  появления `is_admin`) пункт «Администрирование» появляется без повторного
  логина; Sidebar получает актуальный `is_admin`.

### Изменено

- Версия `1.5.0` в `pyproject.toml`, FastAPI, Docker Compose (dev/prod/edge)
  и `frontend/package.json`.

## [1.4.0] — 2026-11-04

### Добавлено

#### Админ-панель заявок (T-120)

- `users`: поля `is_admin` и `must_change_password` (boolean, default false);
  `access_requests`: аудит `reviewed_at`, `reviewed_by`, `approved_user_id`,
  `rejection_reason`.
- Зависимость `get_current_admin` и защищённые эндпоинты:
  `GET /v1/admin/access-requests?status=pending`,
  `POST /v1/admin/access-requests/{id}/approve` (создаёт пользователя с
  временным паролем из `secrets.token_urlsafe` и `must_change_password=True`,
  возвращает пароль один раз),
  `POST /v1/admin/access-requests/{id}/reject` (причина отказа).
- `/v1/auth/login` и `/v1/auth/me` возвращают `is_admin` и
  `must_change_password`; смена пароля сбрасывает флаг.
- React: вкладка **«Администрирование»** в сайдбаре (только для админов),
  страница `AdminDashboard` с таблицей заявок, фильтрами, модалками
  approve/reject, показом временного пароля с копированием.
- `scripts/migrate_admin_panel.py` — идемпотентная миграция существующей БД
  (create_all + мягкие ALTER TABLE), запускается в контейнере без флагов.

### Изменено

- Версия `1.4.0` в `pyproject.toml`, FastAPI, Docker Compose (dev/prod/edge)
  и `frontend/package.json`.

## [1.3.0] — 2026-11-04

### Добавлено

#### Prometheus-метрики (T-117)

- `prometheus-fastapi-instrumentator`: `GET /metrics` со стандартными
  HTTP-метриками (`http_requests_total`, `http_request_duration_seconds`) и
  кастомными `vet_llm_*` / `vet_rag_*`.
- Метрики инференса: вызовы модели по режимам (`chat`/`stream`,
  `success`/`empty`/`error`), токены промпта и генерации, полное время
  генерации, время до первого токена SSE и скорость генерации токенов/с.
- Метрики RAG: поиски (`hit`/`miss`/`error`), число извлечённых чанков,
  длительность поиска и gauge `vet_rag_index_ready` (1/0).
- `llama-cpp-python` не поддерживает `--metrics` и не отдаёт тайминги
  llama.cpp server, поэтому `vet_llm_*` считаются в API по `usage` и времени
  вызова; для стриминговых ответов точны латентность и TTFT.
- В lifespan API добавлена проверка индекса ChromaDB: если его нет, API
  стартует без RAG и пишет предупреждение в лог.

#### RAG production readiness

- `scripts/ingest_knowledge.py` обновляет индекс инкрементально через
  `upsert`, не удаляя коллекцию: существующие чанки (77 в production)
  сохраняются, изменённые обновляются, новые добавляются. Полная пересборка
  — только с флагом `--rebuild`.
- Entrypoint по-прежнему собирает индекс до запуска API при
  `VET_API_AUTO_INGEST=1`; при ошибке API стартует без RAG, если
  `VET_API_INGEST_STRICT=0`.
- `DEPLOYMENT.md`: загрузка статей через `scp`, ручное обновление и полная
  пересборка индекса, проверка `/metrics`, список метрик и пример
  scrape-конфига Prometheus.

### Изменено

- Версия `1.3.0` в `pyproject.toml`, FastAPI, Docker Compose (dev/prod/edge)
  и `frontend/package.json`.

### Фаза 3 завершена (production)

- **Prometheus** собирает `vetassistant-api:8000/metrics` по сети `edge`:
  стандартные HTTP-метрики и 10 кастомных `vet_llm_*` / `vet_rag_*`.
- **Grafana** развёрнута и настроена рядом с Prometheus; дашборды — RPS и p95
  HTTP-латентности, токены/с, p95 TTFT, доля RAG-hit и алерт
  `vet_rag_index_ready == 0`.
- **RAG в production:** коллекция `msd_vet_manual` содержит **77 чанков** из
  двух статей MSD Vet Manual и трёх демо-файлов; API отдаёт
  `vet_rag_index_ready 1.0`, тестовый запрос про парацетамол дал RAG-hit.
- Инкрементальный ingest через `upsert` сохраняет базу при обновлении статей;
  `--rebuild` — только осознанная полная пересборка.
- Публичный путь `/api/metrics` закрыт в Caddy; Prometheus ходит на
  внутренний адрес API.

### Исправлено

- `scripts/ingest_knowledge.py`: пути по умолчанию теперь считаются от
  текущей рабочей директории (`/app/data/knowledge` и `/app/data/chroma_db`
  в контейнере), а не от `PROJECT_ROOT`, который в установленном пакете
  указывал на `site-packages`. Обновление RAG больше не требует
  `--knowledge-dir`/`--chroma-dir`.

## [1.2.1] — 2026-11-04

### Изменено

- **Split architecture:** landing page on `ai-pets.ru`, app on
  `app.ai-pets.ru`, fixed Caddy matchers.
- Лендинг и приложение разделены по доменам: `ai-pets.ru` отдаёт статический
  лендинг (`vetassistant-landing`), `app.ai-pets.ru` — React SPA и
  `/api/*` → `vetassistant-api:8000`, `www.ai-pets.ru` редиректит на apex.
  Caddy на edge-хосте переключён, сертификат поддомена выпущен автоматически,
  smoke-проверки (корень, app, API, `www`, `/privacy/`, `/terms/`) пройдены.
- **Caddy matchers:** служебные файлы лендинга (`README.md`, `DEPLOY.md`,
  `nginx.conf`, `compose.edge.fragment.yml`, `Caddyfile.edge.snippet`)
  возвращают 404 до проксирования. В исходной конфигурации
  `respond @landing_private 404` не срабатывал раньше `handle`; исправлено на
  `handle @landing_private { respond 404 }` (`f982cd0`).

### Документация

- `docs/development/PHASE2_LANDING_APP.md` — Пакеты A и B отмечены как
  реализованные и задеплоенные, добавлен итоговый статус доменов.
- `README.md` — архитектура двух доменов и актуальный smoke-тест.

## [1.2.0] — 2026-11-04

### Добавлено

#### Закрытый доступ (Access Requests)

- Таблица `access_requests` (`email`, `reason`, `status`, `created_at`) и
  публичный эндпоинт `POST /v1/access/request` с ответом `202 Accepted`.
- `slowapi` и лимит **3 заявки в час с одного IP**; повторная заявка с тем же
  email не создаёт дубликат и не раскрывает наличие аккаунта.
- Публичная регистрация закрыта: `POST /v1/auth/register` всегда возвращает
  `403 Регистрация только по заявкам`.
- React: вкладка регистрации убрана, добавлена кнопка «Запросить доступ» с
  модальной формой; `?mode=request` автоматически открывает её (deep-link с
  лендинга).
- Админские скрипты: `scripts/list_access_requests.py` и
  `scripts/create_user.py` для ручного создания аккаунта после одобрения.

#### Лендинг и Nginx

- Каталог `landing/`: статический лендинг `ai-pets.ru`, страницы
  `/privacy/`, `/terms/`, `404.html`, `robots.txt`, `sitemap.xml`, OG-карточка.
- `landing/nginx.conf`: кеширование статики, security-заголовки, `/healthz` и
  отдача юридических страниц.
- Фрагменты `landing/compose.edge.fragment.yml` и
  `landing/Caddyfile.edge.snippet` для последующего переключения Caddy и
  поддомена `app.ai-pets.ru` (в этом релизе не применяются).
- `landing/DEPLOY.md` с порядком выкладки, smoke-проверками и откатом.

## [1.1.3] — 2026-11-04

### Безопасность

- **Security key rotation.** SSH-ключ пользователя `deployer` перевыпущен,
  старый отозван; GitHub Secret `SSH_KEY` обновлён. Тег `v1.1.3` проверяет
  автоматический деплой с новым ключом.
- В релиз также входит T-110: автоматическая сборка ChromaDB перед стартом
  API и кеширование модели эмбеддингов в volume `hf_cache`.

## [1.1.2] (Unreleased)

### Исправлено

- **Fix deploy timeout.** Полная Docker-сборка edge-стека на сервере занимает
  около 50 минут, поэтому лимиты workflow увеличены: `timeout-minutes` с
  `30` до `90`, `command_timeout` с `20m` до `80m`.
- Версия поднята до `1.1.2`; тег `v1.1.2` проверяет автоматический деплой
  с новыми таймаутами.

## [1.1.1] (Unreleased)

### Тестовый релиз

- Тег `v1.1.1` создан для проверки нового CI/CD-пайплайна: сборки образов
  и автоматического деплоя edge-стека через `.github/workflows/deploy.yml`.
- Версия поднята до `1.1.1`; функциональных изменений относительно `1.1.0`
  нет.

## [1.1.0] — 2026-11-04

### Добавлено

#### Безопасность и память

- **Смена пароля (T-103).** Эндпоинт `POST /v1/auth/change-password`
  принимает `old_password`, `new_password` и необязательный
  `new_password_confirm`, проверяет старый bcrypt-хэш и сохраняет новый.
  В React-сайдбаре добавлена кнопка-шестерёнка «Настройки» с модальной
  формой смены пароля; после успеха показывается уведомление
  «Пароль изменен» и выполняется разлогин. Добавлены тесты на успешную
  смену, неверный старый пароль и несовпадение подтверждения.
- **Конфигурация памяти (T-101).** `VET_API_N_CTX` по умолчанию снижен с
  `8192` до `4096` в `app/settings.py`, Docker Compose и
  `.env.production.example`; при OOM рекомендуется `2048`. `/health`
  теперь возвращает `n_ctx`, `n_threads` и `n_gpu_layers`, добавлен
  `scripts/check_ram.py` для мониторинга конфигурации и памяти хоста.
- **Защита сервера (T-104).** Добавлен `scripts/setup_ufw.sh`:
  разрешает SSH (`22`), HTTP (`80`) и HTTPS (`443`), запрещает входящие
  по умолчанию и включает UFW; в `DEPLOYMENT.md` добавлен раздел
  «Безопасность сервера» с инструкцией запуска.

### Планируется

- Расширенный Safety-бенчмарк и независимые модели-судьи.
- Расширение базы знаний и оценка качества RAG-ответов.
- Rate limiting на `/v1/auth/login` и публичных эндпоинтах.
- Инвалидация ранее выданных JWT при смене пароля (T-105, backlog).

## [1.0.0] — 2026-11-03

> **Первый production-ready релиз VetAssistant.** Тег: `v1.0.0`
> (публикуется после боевой проверки HTTPS на VPS).

VetAssistant прошёл путь от идеи и синтетических данных до полноценного
multi-tenant SaaS: локальная LLM-модель, RAG по MSD Vet Manual, Agentic
Loop с записью к ветеринару, React-интерфейс, Telegram-бот, JWT-авторизация
и production-деплой на одном домене с HTTPS.

### Путь к 1.0.0

| Этап | Что появилось |
|---|---|
| v0.1.0 | Пайплайн генерации данных, первые промпты, RAG-заготовка |
| v0.2.0 | FastAPI, Streamlit UI, живая GGUF-модель, MSD Vet Manual |
| v0.3.0 | Autonomous Agent: `book_appointment`, `set_reminder`, PostgreSQL |
| v0.4.0 | Telegram-бот на aiogram 3.x, история диалогов, Function Calling |
| v0.5.0 | React 19 SPA: SSE-стриминг, Markdown, «Мои записи», Docker/Nginx |
| T-039 | JWT Auth, bcrypt, `user_id` FK и мультитенантная изоляция |
| T-040 | Production Docker, единый домен, Let's Encrypt/Certbot, deploy.sh |
| **v1.0.0** | **Production Ready: безопасность, HTTPS, эксплуатационная документация** |

### Добавлено в 1.0.0

#### Multi-tenant SaaS и безопасность

- JWT-аутентификация (`PyJWT`, HS256) и bcrypt-хэширование паролей через
  `passlib[bcrypt]`; эндпоинты `/v1/auth/register`, `/v1/auth/login` и
  `/v1/auth/me` (T-039).
- Таблица `users` и `user_id` с внешним ключом в `appointments` и
  `reminders`; мягкая миграция старых таблиц без потери строк (T-039).
- Мультитенантная изоляция: `/v1/chat/completions`, `/v1/appointments`,
  `/v1/reminders` и `/v1/tools/execute` требуют Bearer-токен и работают
  только с данными текущего пользователя; Agentic Loop берёт `user_id` из
  JWT (T-039).
- React: экран входа/регистрации, JWT в `localStorage`, заголовок
  `Authorization` во всех запросах, кнопка «Выйти» и раздельная история чата
  по `user_id` (T-039).
- Streamlit: формы входа/регистрации, токен в `session_state`, кнопка
  «Выйти» и авторизованные запросы (T-039).
- Telegram: синтетический аккаунт `telegram-<id>@bot.vetassistant.local`,
  детерминированный HMAC-пароль, кэш JWT и повторная авторизация при `401`
  (T-039).

#### Production-инфраструктура

- `docker-compose.prod.yml`: публикация только `frontend:80`; API и
  PostgreSQL доступны только внутри Docker-сети; сервис бота удалён из
  production (T-040, T-043).
- `docker-compose.ssl.yml`: `443`, Certbot, Let's Encrypt, HSTS и
  HTTP→HTTPS-редирект; единый домен через Nginx (T-040).
- `frontend/nginx.conf`: проксирование `/api/*` в `api:8000`, SSE без
  буферизации, SPA fallback, ACME webroot и security-заголовки (T-040).
- `.env.production.example` с обязательными секретами и инструкцией
  `openssl rand -hex 32`; `.env` и каталоги Certbot исключены из Git (T-040).
- `scripts/deploy.sh`: установка Docker/Compose на Ubuntu, клонирование,
  генерация секретов, запуск production-стека и опциональный `--ssl`;
  `scripts/renew_ssl.sh` для автопродления сертификата (T-040).
- `docker-compose.edge.yml`: edge-стек для общего VPS с Caddy — `api`,
  `db`, `frontend`, внешняя сеть `edge`, изолированная `internal`, без
  публикации 80/443, бота и Streamlit (T-043).
- `deploy/Caddyfile`: `ai-pets.ru`, редирект `www`, `/api/*` → `api:8000`
  со снятием префикса и SPA через `frontend:80` (T-043).
- `scripts/upload_model.py`: SFTP-загрузка GGUF в
  `/srv/vetassistant/data/gguf/` через `.part`, проверка размера и
  SHA-256 (`45cccc...b10b`) и атомарное переименование (T-043).
- `VET_API_ALLOW_PUBLIC_REGISTRATION`: production-флаг закрытия публичной
  регистрации; при `false` `/v1/auth/register` возвращает `403`
  «Регистрация временно закрыта» (T-043).
- `DEPLOYMENT.md`: аренда VPS, DNS A-запись, firewall, модель GGUF, Certbot,
  HTTPS-редирект, обновления, бэкапы и диагностика (T-040).
- `SECURITY.md`: политика безопасности, порядок сообщения об уязвимостях,
  модель угроз, известные ограничения и обязательный production-чеклист
  (T-041).

#### Качество и релизная инженерия

- Тесты авторизации: `401` без токена, `409` при дубле email, изоляция
  записей между пользователями (T-039).
- Тесты production-конфигурации: compose, HTTPS-overlay, Nginx, шаблон
  секретов и скрипты деплоя (T-040).
- Тесты edge-конфигурации, Caddyfile, SFTP-загрузчика и smoke-теста;
  проверка закрытия регистрации (T-043).
- Smoke-тест адаптирован под закрытую регистрацию: вход существующим
  пользователем, проверка `/api/v1/appointments` (T-045).
- CI: `ruff`, `mypy`, `pytest`, frontend lint/tests/build и Docker-сборка
  API + Frontend.
- Версия `1.0.0` синхронизирована в `pyproject.toml`, FastAPI,
  `docker-compose.yml`, `docker-compose.prod.yml`, `frontend/package.json`
  и lockfile (T-041).

### Изменено

- `VET_API_JWT_SECRET` и `VET_API_ACCESS_TOKEN_EXPIRE_MINUTES` добавлены в
  настройки, `.env.example` и Docker Compose; `VET_BOT_AUTH_SECRET` — в
  настройки бота и Compose (T-039).
- README дополнен разделами об аутентификации, production-деплое и
  финальным статусом **Production Ready** со ссылками на `SECURITY.md` и
  `DEPLOYMENT.md` (T-039, T-040, T-041).
- README дополнен разделом Edge-деплоя для инфраструктурного агента (T-043).
- SSH-оркестратор `deploy_prod.py` и зависимость `paramiko` удалены:
  управление VPS передано инфраструктурному агенту (T-043).
- `deploy.sh` больше не запрашивает `TELEGRAM_BOT_TOKEN`; сервис `bot`
  удалён из production-стека (T-043).
- Dockerfile фронтенда копирует Nginx-конфигурацию с правилами `/api`, SPA
  и ACME для HTTP (T-040).

### Безопасность

- Пароли не хранятся в открытом виде; JWT подписывается секретом и имеет
  срок действия 7 дней по умолчанию (T-039).
- Данные питомцев, записи и напоминания недоступны другим пользователям,
  включая Telegram-аккаунты (T-039).
- Production-стек не публикует API и PostgreSQL наружу; наружу открыты
  только `80`/`443`, а HTTPS включается с HSTS и редиректом с HTTP (T-040).
- Добавлена публичная политика безопасности и обязательный чеклист смены
  `VET_API_JWT_SECRET`, `POSTGRES_PASSWORD` и `VET_BOT_AUTH_SECRET` перед
  публикацией сервиса (T-041).
- Публичная регистрация в production закрывается флагом
  `VET_API_ALLOW_PUBLIC_REGISTRATION=false`; API отвечает `403`
  «Регистрация временно закрыта» (T-043).

### Результаты 1.0.0

| Метрика | Значение |
|---|---|
| Python-тесты | **569 passed** |
| Frontend-тесты | **29 passed** |
| Python-линтеры | `ruff check .`, `mypy app bot` — чисто |
| Frontend | `oxlint`, `npm run build` — успешно |
| Docker Compose | dev, prod и SSL-overlay — валидны |
| Nginx | `nginx -t` для HTTP и HTTPS — успешно |
| Production-проверки | HTTP→HTTPS, HSTS, `/healthz`, SPA fallback |
| CI | Lint & Test, Frontend, Docker Build — success |

### Известные ограничения

- Нет rate limiting, подтверждения email, восстановления пароля и 2FA.
- JWT хранится в `localStorage`; требуется защита от XSS.
- История Telegram-диалога хранится в памяти процесса.
- Модель не заменяет ветеринарного врача; медицинские ограничения описаны
  в README и системном промпте.

## [0.5.0] — 2026-11-03

> Релиз «React web interface». Тег: `v0.5.0`.

Пятый релиз: у VetAssistant появился полноценный веб-интерфейс. React-SPA
работает с тем же FastAPI, стримит ответы через SSE, показывает вызовы
инструментов и объединяет чат, настройки и записи питомцев в одном окне.

### Добавлено

#### React 19 Frontend

- Новый фронтенд `frontend/` на React 19 + Vite + TypeScript + Tailwind CSS 4:
  чат в стиле ChatGPT с боковой панелью и адаптивной вёрсткой (T-037).
- SSE-стриминг ответов `/v1/chat/completions`: текст появляется по мере
  генерации, поддерживается остановка запроса (T-037).
- Markdown и GFM-таблицы через `react-markdown`; вызовы `book_appointment` и
  `set_reminder` отображаются цветными бейджами (T-037).
- Настройки `temperature`, RAG и Function Calling; блок «Мои записи» с
  приёмами (`/v1/appointments`) и напоминаниями (`/v1/reminders`) (T-037).
- История диалога в `localStorage`, индикатор доступности API и кнопка
  «Новый чат» (T-037).

#### Инфраструктура

- `frontend/Dockerfile`: multi-stage сборка Node.js → Nginx, healthcheck
  `/healthz` (T-037).
- Сервис `frontend` в Docker Compose на порту `3000`; Nginx проксирует
  `/api/*` в `api:8000` без буферизации SSE (T-037).
- CORS в FastAPI для Vite (`http://localhost:5173`,
  `http://127.0.0.1:5173`) и Docker-фронтенда на порту `3000` (T-037).
- README: скриншот интерфейса, локальный запуск `npm run dev`, сборка, тесты и
  запуск через Docker на порту `3000` (T-037, T-038).
- CI и Release: отдельная проверка фронтенда (`npm ci`, lint, tests, build)
  и сборка Docker-образов API и Frontend (T-037, T-038).

### Изменено

- Версия проекта, FastAPI-приложения, Docker-образов и `frontend/package.json`
  поднята до `0.5.0`.
- README дополнен разделом о React-интерфейсе, скриншотом и бейджем версии
  `v0.5.0`; зафиксированы порты `3000` (Docker) и `5173` (Vite dev).
- Release-workflow собирает оба Docker-образа — `vetassistant` и
  `vetassistant-frontend` — перед публикацией GitHub Release.

### Результаты v0.5.0

| Метрика | Значение |
|---|---|
| Python-тесты | **518 passed** |
| Frontend-тесты | **22 passed** |
| Python-линтеры | `ruff check .`, `mypy app bot` — чисто |
| Frontend-линтер | `oxlint` — чисто |
| Сборка фронтенда | `npm run build` — успешно |
| Docker Compose | `docker compose config` — валиден |
| Docker-образы | API и Frontend собираются, `/healthz` отвечает 200 |
| E2E | SSE-стриминг, tool badge, «Мои записи», мобильный drawer |

### Известные ограничения

- История чата хранится в `localStorage` браузера и не синхронизируется между
  устройствами.
- Веб-интерфейс не содержит аутентификации и рассчитан на локальный запуск.
- Возможны галлюцинации; ассистент не заменяет ветеринарного врача.

## [0.4.0] — 2026-11-03

> Релиз «Telegram-бот». Тег: `v0.4.0`.
> Тег создаётся после проверки бота в Telegram.

Четвёртый релиз: у VetAssistant появился полноценный интерфейс для
владельцев животных в Telegram. Бот работает отдельным процессом, помнит
контекст диалога и использует тот же локальный API с RAG и Function Calling.

### Добавлено

#### Telegram-бот

- Пакет `bot/` на aiogram 3.x: отдельный процесс `python -m bot` и
  отдельный контейнер `bot` (T-035).
- Команды `/start` (приветствие и дисклеймер «ИИ, а не живой врач»),
  `/reset` (очистка истории) и `/help` (справка) (T-035).
- История диалога для каждого Telegram `user_id`: бот передаёт предыдущие
  сообщения в FastAPI, поэтому помнит контекст беседы (T-035).
- Обработка ошибок API: недоступный сервер, таймаут, `503` и отклонение
  запроса системой безопасности показываются пользователю понятным текстом
  (T-035).
- Автоматическое разбиение длинных ответов на части в пределах лимита
  сообщения Telegram (T-035).

#### Function Calling в Telegram

- Бот передаёт `tools` в `POST /v1/chat/completions` и поддерживает
  `book_appointment` и `set_reminder` (T-035).
- Подтверждения выполнения инструментов отображаются человекочитаемо:
  «✅ Я записал вашего питомца на приём…» и «⏰ Напоминание создано…»,
  после чего показывается финальный текст модели (T-035).

#### Инфраструктура и документация

- Docker Compose сервис `bot` с зависимостью от здорового `api`,
  переменной `TELEGRAM_BOT_TOKEN` и настройками `VET_BOT_*` (T-035).
- `Dockerfile` включает пакет `bot`; wheel также содержит `bot/` (T-035).
- README: получение токена у @BotFather, локальный запуск, запуск в Docker
  Compose и таблица настроек бота (T-035).

#### Тесты

- Юнит-тесты HTTP-клиента FastAPI: нормализация URL, сборка payload,
  парсинг ответа и `tool_calls`, маппинг ошибок (T-035).
- Юнит-тесты логики бота с фейковыми Telegram и FastAPI: команды, история
  по пользователям, Function Calling, разбиение длинных ответов (T-035).
- Всего в проекте **516 тестов**.

### Изменено

- Версия проекта, FastAPI-приложения и Docker-образа поднята до `0.4.0`.
- README дополнен разделом о Telegram-боте и бейджем версии `v0.4.0`.

### Результаты v0.4.0

| Метрика | Значение |
|---|---|
| Тесты | **516 passed** |
| Линтеры | `ruff check .`, `mypy app bot` — чисто |
| Docker Compose | `docker compose config` — валиден |
| Сборка wheel | пакет `bot/` включён |
| Запуск без токена | код 1 и понятная ошибка про `TELEGRAM_BOT_TOKEN` |

### Известные ограничения

- История диалога хранится в памяти процесса бота и сбрасывается после его
  перезапуска; приёмы и напоминания при этом остаются в PostgreSQL.
- Бот рассчитан на один экземпляр и не содержит rate limiting.
- Function Calling зависит от способности модели сформировать корректный
  JSON; при ошибке пользователь получает понятное сообщение.
- Возможны галлюцинации; ассистент не заменяет ветеринарного врача.

## [0.3.0] — 2026-11-03

> Стабильный релиз «Autonomous Agent». Тег: `v0.3.0`.

Третий релиз: ассистент стал автономным агентом — вызывает инструменты,
сохраняет записи в базе данных и опирается на реальные статьи MSD Vet Manual.

### Добавлено

#### Function Calling и Agentic Loop

- Function Calling: `app/tools.py` со схемами `book_appointment` и
  `set_reminder`, парсинг нативных и текстовых `tool_calls`, поддержка
  параметра `tools` в `/v1/chat/completions` (T-030).
- Agentic Loop: API выполняет `tool_calls`, передаёт результат обратно модели
  и возвращает финальный текст; в ответе вызовы остаются как индикация для UI
  (T-032).
- Прямой эндпоинт `POST /v1/tools/execute` для выполнения инструментов (T-030).
- Streamlit UI: переключатель Function Calling и бейджи
  «🛠️ Вызван инструмент: …» с параметрами (T-030, T-032).

#### База данных

- PostgreSQL 16 в Docker Compose (`db`), volume `postgres_data`,
  healthcheck и переменные `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB`
  (T-033).
- Async SQLAlchemy 2.0: модели `Appointment`/`Reminder`, `asyncpg` для
  PostgreSQL и `aiosqlite` для локальных тестов; создание таблиц в lifespan
  FastAPI (T-033).
- Реальное сохранение приёмов и напоминаний; read-эндпоинты
  `GET /v1/appointments` и `GET /v1/reminders` (T-033).
- Streamlit: expander **«Мои записи»** с карточками приёмов и напоминаний
  (T-033).

#### Реальный RAG

- `scripts/download_msd.py` скачивает статьи MSD Vet Manual в
  `data/knowledge/real/` (T-030).
- `scripts/ingest_knowledge.py` рекурсивно читает TXT и PDF через `pypdf`,
  режет текст на чанки и строит эмбеддинги в ChromaDB (T-030).
- API добавляет найденные фрагменты в system prompt как «Справочная информация
  из MSD Vet Manual» при `use_rag=true` (T-026, T-030).

#### UI и релизная инфраструктура

- Streamlit UI: потоковый чат, история, `temperature`, RAG, Function Calling
  и «Мои записи» (T-025, T-030, T-033).
- GitHub Release `v0.2.0 - VetAssistant MVP` с описанием из CHANGELOG (T-031).
- Workflow `.github/workflows/release.yml`: на пуш тега `v*` собирает
  Docker-образ и создаёт GitHub Release через `softprops/action-gh-release@v2`
  (T-031).
- Бейдж последнего релиза в README (T-031).

### Изменено

- SQLite-хранилище T-032 заменено на async SQLAlchemy/PostgreSQL (T-033).
- README дополнен разделами о Function Calling, базе данных и реальном RAG.
- Версия проекта и Docker-образа поднята до `0.3.0`.

### Результаты v0.3.0

| Метрика | Значение |
|---|---|
| Тесты | **487 passed** |
| Линтеры | `ruff check .`, `mypy app` — чисто |
| PostgreSQL 16 | проверено на реальном контейнере, данные сохраняются в volume |
| RAG | 2 статьи MSD Vet Manual, поддержка TXT/PDF |
| Инструменты | `book_appointment`, `set_reminder` + Agentic Loop |
| CI (GitHub Actions) | Lint & Test + Docker Build — success |

### Известные ограничения

- База знаний пока небольшая (2 реальные статьи MSD + демо-файлы); качество
  RAG-ответов отдельно не измерялось.
- Function Calling зависит от способности модели формировать корректный JSON;
  при ошибке API возвращает понятную ошибку выполнения инструмента.
- Safety-набор по-прежнему мал, а LLM-Judge — та же модель, что и оцениваемая.
- Возможны галлюцинации; ассистент не заменяет ветеринарного врача.

## [0.2.0] — 2026-11-03

> Официальный стабильный релиз. Тег: `v0.2.0`.
> CI: GitHub Actions, прогон `41527072842` — success.

Второй релиз: Streamlit UI, локальная RAG-база знаний, Router & Triage,
Docker-стек для запуска всего приложения одной командой и CI/CD-пайплайн.

### Добавлено

- Streamlit-интерфейс `app/ui.py`: чат с историей в `st.session_state`,
  потоковый вывод SSE, слайдер `temperature`, очистка истории и понятная
  ошибка при выключенном FastAPI (T-025).
- HTTP-клиент UI `app/ui_client.py` с тестами парсинга SSE (T-025).
- RAG-слой: `scripts/ingest_knowledge.py`, ChromaDB + sentence-transformers,
  поиск по `data/knowledge/` и контекст «Справочная информация из MSD Vet
  Manual» в system prompt при `use_rag=true` (T-026).
- Галочка «Использовать базу знаний (RAG)» в Streamlit-сайдбаре (T-026).
- Router & Triage: `app/router.py` с быстрыми эвристиками экстренных
  симптомов и prompt injection. API отклоняет инъекции с `400 Bad Request`
  и добавляет жёсткую инструкцию «СРОЧНО ОБРАТИТЕСЬ В КЛИНИКУ» при
  угрожающих жизни симптомах до вызова LLM (T-027).
- Бенчмарк роутера `data/router_benchmark.jsonl` (30 кейсов: экстренные,
  обычные, инъекции) и `scripts/evaluate_router.py` с Precision/Recall/F1;
  отчёт `docs/development/reports/EVAL_ROUTER.md` (T-013).
- `UISettings` (`VET_UI_API_URL`, `VET_UI_MODEL_ID`, `VET_UI_TIMEOUT_S`) —
  адрес API можно переопределить для Docker и других окружений.
- Docker-стек: `Dockerfile`, `docker-compose.yml`, `.dockerignore`.
  Контейнеры FastAPI (`:8000`) и Streamlit UI (`:8501`), общий volume
  `./data:/app/data` для GGUF-модели и ChromaDB.
- CI/CD: GitHub Actions workflow `.github/workflows/ci.yml` на push/PR в
  `main` — `ruff check .`, `mypy app`, `pytest -q` и сборка Docker-образа;
  бейдж статуса CI в README (T-028).
- README: инструкция запуска через `docker compose up --build`.

### Результаты v0.2.0

| Метрика | Значение |
|---|---|
| Router: экстренность F1 | **1.0000** |
| Router: prompt injection F1 | **1.0000** |
| Бенчмарк роутера | 30 кейсов, 0 ошибок |
| Проверка Docker Compose | `docker compose config` — OK |
| Сборка Docker-образа | `docker compose build api` — OK (3.68 ГБ) |
| Smoke-тест контейнеров | API `/health` 200, UI `/_stcore/health` — `ok` |
| Тесты | **447 passed** |
| CI (GitHub Actions) | **Lint & Test + Docker Build — success** |

### Планируется

- Function Calling для ассистента.
- Расширение RAG реальными ветеринарными справочниками.
- Расширенный Safety-бенчмарк и независимые модели-судьи.
- Интеграция с внешним веб-приложением.

## [0.1.0] — 2026-11-02

Первый публичный релиз: данные, обученная GGUF-модель, оценка качества,
Safety-проверка и локальный OpenAI-совместимый API.

### Добавлено

- **Инфраструктура и пайплайн данных:** `pyproject.toml`, настройки через
  `pydantic-settings`, клиент учителя с ретраями и логированием токенов
  (T-001, T-002).
- **Генерация синтетических данных:** Шаг A (вопросы владельцев), Шаг B
  (многотурные диалоги), Safety-кейсы, PII-фильтр и дедупликация
  (T-003, T-004, T-005).
- **Масштабирование:** мультипровайдерная конфигурация, bulk-генерация с
  конкурентностью и resume, датасет v1 — 8 120 bulk + 500 safety, после
  PII/дедупа 8 275; train 7 448 / val 827 (T-008, T-009, T-010).
- **PetQA:** загрузка и перевод 10 076 сырых записей, 8 076 seed-вопросов,
  PetQA-Bench на 2 000 open-ended вопросов (T-011).
- **GigaChat:** OAuth 2.0, кеш токена, ограничение конкурентности (T-012).
- **DVC/S3 Selectel:** 13 путей под DVC, `dvc push/pull`, `scripts/sync_data.py`
  (T-014).
- **Обучение:** QLoRA SFT Qwen3-8B, `scripts/train_sft.py`, merge LoRA,
  dry-run и тесты без GPU (T-015).
- **GGUF:** конвертация в f16/Q4_K_M/Q5_K_M, `scripts/convert_to_gguf.py`
  (T-018).
- **Eval harness:** `evaluation/evaluate.py`, MCQ/Reasoning/Safety-метрики,
  LLM-Judge, OpenAI-совместимые endpoint'ы, resume и инкрементальный кеш
  ответов и вердиктов (T-006, T-007, T-020, T-021).
- **FastAPI-обёртка:** `app/main.py`, `POST /v1/chat/completions` в формате
  OpenAI, SSE-стриминг, ветеринарный system prompt, `GET /health`,
  `llama-cpp-python` (T-022).
- **Safety-проверка:** `scripts/test_safety.py` — Safety-кейсы из
  `data/eval_dataset.jsonl` через локальный API (T-023).
- **Документация:** `README.md` с инструкцией для Windows, `MODEL_CARD.md`,
  `docs/development/reports/EVAL_V1.md`, этот CHANGELOG (T-023, T-024).

### Изменено

- `evaluation/evaluate.py`: добавлены `--skip-generation`, `--judge-output`,
  `--local-api` и метаданные судьи в отчёте.
- `evaluation/judge.py`: structured output `json_schema` для LM Studio,
  `CachingJudge` для resume длинных прогонов.
- Ошибки API судьи по отдельным записям больше не прерывают весь прогон.

### Исправлено

- Падения прогона из-за выгрузки модели в LM Studio: ответы и вердикты
  сохраняются инкрементально и переиспользуются при resume.
- Невалидный JSON судьи при обычном текстовом ответе: включён строгий
  `response_format: json_schema`.
- Отсутствующий файл ответов теперь даёт понятную ошибку вместо traceback.

### Результаты релиза

| Метрика | Значение |
|---|---|
| `train_loss` | 0.5922 |
| `eval_loss` | 0.483 |
| Ответов сгенерировано (PetQA) | 2000 / 2000 |
| `reasoning_score_avg` (LLM-Judge) | **4.5185** |
| `reasoning_above_4_ratio` | **0.977** |
| Safety через локальный API | **passed=2, failed=0** |
| Тесты | 377 passed |

### Известные ограничения

- Safety-набор мал (2 кейса); нужен расширенный бенчмарк.
- LLM-Judge — та же модель, что и оцениваемая (self-evaluation bias).
- `reference_f1_avg` не показательна из-за разницы длины ответов и эталонов.
- Возможны галлюцинации; модель не заменяет ветеринарного врача.
