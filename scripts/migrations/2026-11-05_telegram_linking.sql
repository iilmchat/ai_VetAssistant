-- ============================================================================
-- VetAssistant v1.6.0 — привязка Telegram к веб-аккаунту (T-134.1)
--
-- Назначение: подготовить прод-БД ДО деплоя нового кода API. Схема появляется
-- заранее, а `create_all` при старте API видит уже готовые колонку и таблицу
-- (новый код умеет докатывать их и сам — этот скрипт нужен, чтобы не зависеть
-- от старта приложения и облегчить откат образа).
--
-- Запуск на сервере (PostgreSQL 16), из корня /srv/vetassistant:
--   docker compose -f docker-compose.edge.yml exec -T db \
--     sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' \
--     < scripts/migrations/2026-11-05_telegram_linking.sql
--
--   Переменные POSTGRES_USER/POSTGRES_DB уже заданы внутри контейнера db,
--   пароль не нужен: psql ходит по локальному сокету.
--
-- Проверка после применения:
--   docker compose -f docker-compose.edge.yml exec -T db \
--     sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\d users"'
--
-- Скрипт идемпотентен: повторный запуск не меняет данные и не падает.
-- Время выполнения: секунды; блокировка users — на время ALTER TABLE.
-- ============================================================================

BEGIN;

-- 1. users.telegram_id -------------------------------------------------------
-- NULL — Telegram не привязан. BIGINT: Telegram ID уже превышает 2^31.
ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_id BIGINT;

-- Один Telegram-аккаунт может быть привязан только к одному пользователю.
-- NULL-значения уникальность не нарушают (в PostgreSQL NULL <> NULL),
-- поэтому несколько непривязанных пользователей допустимы.
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_telegram_id
    ON users (telegram_id);

-- 2. telegram_link_codes -----------------------------------------------------
-- Одноразовые коды привязки. Хранится только HMAC-SHA256 (64 hex-символа):
-- по этой таблице невозможно восстановить код, который видел пользователь.
CREATE TABLE IF NOT EXISTS telegram_link_codes (
    id           SERIAL PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code_hash    VARCHAR(64) NOT NULL,
    telegram_id  BIGINT,
    expires_at   TIMESTAMP WITH TIME ZONE NOT NULL,
    used_at      TIMESTAMP WITH TIME ZONE,
    created_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Поиск кода при подтверждении идёт по хэшу: уникальный индекс обязателен.
CREATE UNIQUE INDEX IF NOT EXISTS ix_telegram_link_codes_code_hash
    ON telegram_link_codes (code_hash);

-- Коды пользователя: подсчёт активных (не больше 3) и отзыв остальных.
CREATE INDEX IF NOT EXISTS ix_telegram_link_codes_user_id
    ON telegram_link_codes (user_id);

-- Очистка просроченных кодов.
CREATE INDEX IF NOT EXISTS ix_telegram_link_codes_expires_at
    ON telegram_link_codes (expires_at);

COMMIT;

-- ============================================================================
-- Проверка после COMMIT (выполните отдельно, вне транзакции):
--
--   SELECT column_name, data_type, is_nullable
--     FROM information_schema.columns
--    WHERE table_name = 'users' AND column_name = 'telegram_id';
--   -- ожидается: telegram_id | bigint | YES
--
--   SELECT indexname, indexdef
--     FROM pg_indexes
--    WHERE tablename IN ('users', 'telegram_link_codes')
--      AND indexname LIKE 'ix_%telegram%'
--    ORDER BY tablename, indexname;
--   -- ожидается 4 индекса: ix_users_telegram_id (UNIQUE),
--   -- ix_telegram_link_codes_code_hash (UNIQUE), _user_id, _expires_at
--
--   SELECT count(*) FROM users WHERE telegram_id IS NOT NULL;
--   -- после миграции: 0 (привязки появятся при работе нового кода)
--
-- Откат (только после откачки API на предыдущую версию!):
--   BEGIN;
--   DROP TABLE IF EXISTS telegram_link_codes;
--   DROP INDEX IF EXISTS ix_users_telegram_id;
--   ALTER TABLE users DROP COLUMN IF EXISTS telegram_id;
--   COMMIT;
-- ============================================================================
