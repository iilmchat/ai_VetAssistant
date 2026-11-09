-- ============================================================================
-- VetAssistant v1.9.0 — обратная связь по ответам 👍/👎 (T-139.1)
--
-- Назначение: подготовить прод-БД ДО деплоя нового кода API. Таблица feedback
-- создаётся заранее, а `create_all` при старте API видит уже готовую схему
-- (новый код создаёт её и сам — скрипт нужен, чтобы не зависеть от старта
-- приложения и облегчить откат образа).
--
-- Приватность (152-ФЗ): в таблице НЕТ текстов диалогов. Хранятся только
-- идентификатор пользователя, непрозрачный идентификатор сообщения на
-- клиенте (message_id), оценка 1/-1 и время. По этой схеме невозможно
-- восстановить содержание переписки.
--
-- Запуск на сервере (PostgreSQL 16), из корня /srv/vetassistant:
--   docker compose -f docker-compose.edge.yml exec -T db \
--     sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' \
--     < scripts/migrations/2026-11-09_feedback.sql
--
--   Переменные POSTGRES_USER/POSTGRES_DB уже заданы внутри контейнера db,
--   пароль не нужен: psql ходит по локальному сокету.
--
-- Проверка после применения:
--   docker compose -f docker-compose.edge.yml exec -T db \
--     sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\d feedback"'
--
-- Скрипт идемпотентен: повторный запуск не меняет данные и не падает.
-- Время выполнения: секунды; блокировок на users нет (только новая таблица).
-- ============================================================================

BEGIN;

-- 1. feedback ----------------------------------------------------------------
-- Одна оценка на пользователя и сообщение: UNIQUE(user_id, message_id).
-- Повторная оценка перезаписывает прежнюю (API делает upsert), поэтому
-- история по одному сообщению не раздувается.
--
-- user_id удаляется каскадом вместе с аккаунтом, чтобы после DELETE
-- пользователя не оставалось осиротевших оценок. API дополнительно удаляет
-- их явно (SQLite в тестах не форсирует FK).
CREATE TABLE IF NOT EXISTS feedback (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message_id  VARCHAR(128) NOT NULL,
    rating      SMALLINT NOT NULL,
    created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_feedback_rating
        CHECK (rating IN (1, -1)),
    CONSTRAINT uq_feedback_user_message
        UNIQUE (user_id, message_id)
);

-- Индексы: по пользователю (его оценки / удаление аккаунта) и по сообщению
-- (проверка существующей оценки при upsert).
CREATE INDEX IF NOT EXISTS ix_feedback_user_id
    ON feedback (user_id);
CREATE INDEX IF NOT EXISTS ix_feedback_message_id
    ON feedback (message_id);

COMMIT;

-- ============================================================================
-- Проверка после COMMIT (выполните отдельно, вне транзакции):
--
--   SELECT column_name, data_type, is_nullable, column_default
--     FROM information_schema.columns
--    WHERE table_name = 'feedback'
--    ORDER BY ordinal_position;
--   -- ожидается 5 колонок: id, user_id, message_id, rating, created_at
--
--   SELECT conname, pg_get_constraintdef(oid)
--     FROM pg_constraint
--    WHERE conrelid = 'feedback'::regclass;
--   -- ожидается uq_feedback_user_message UNIQUE (user_id, message_id),
--   -- ck_feedback_rating CHECK (rating = ANY (ARRAY[1, -1])) и FK на users
--
--   SELECT count(*) FROM feedback;
--   -- сразу после миграции: 0 (оценки появятся при работе нового кода)
--
-- Откат (только после откачки API на предыдущую версию!):
--   BEGIN;
--   DROP TABLE IF EXISTS feedback;
--   COMMIT;
-- ============================================================================
