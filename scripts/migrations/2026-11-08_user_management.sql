-- ============================================================================
-- VetAssistant v1.8.0 — управление пользователями (T-140.1)
--
-- Назначение: подготовить прод-БД ДО деплоя нового кода API. Схема появляется
-- заранее, а `create_all` при старте API видит уже готовые колонку и таблицу
-- (новый код умеет докатывать их и сам — этот скрипт нужен, чтобы не зависеть
-- от старта приложения и облегчить откат образа).
--
-- Запуск на сервере (PostgreSQL 16), из корня /srv/vetassistant:
--   docker compose -f docker-compose.edge.yml exec -T db \
--     sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' \
--     < scripts/migrations/2026-11-08_user_management.sql
--
--   Переменные POSTGRES_USER/POSTGRES_DB уже заданы внутри контейнера db,
--   пароль не нужен: psql ходит по локальному сокету.
--
-- Проверка после применения:
--   docker compose -f docker-compose.edge.yml exec -T db \
--     sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\d users"'
--   docker compose -f docker-compose.edge.yml exec -T db \
--     sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\d admin_actions"'
--
-- Скрипт идемпотентен: повторный запуск не меняет данные и не падает.
-- Время выполнения: секунды; блокировка users — на время ALTER TABLE.
-- ============================================================================

BEGIN;

-- 1. users.is_active ---------------------------------------------------------
-- Блокировка действует сразу: get_current_user проверяет флаг на каждом
-- запросе, поэтому уже выданный JWT перестаёт работать без отзыва токенов.
-- Все существующие пользователи остаются активными.
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;

-- 2. admin_actions -----------------------------------------------------------
-- Журнал действий администраторов. admin_id обнуляется при удалении
-- администратора (ON DELETE SET NULL), а target_user_id намеренно хранится без
-- внешнего ключа: запись action='delete' должна сохранить id удалённого
-- пользователя для аудита.
CREATE TABLE IF NOT EXISTS admin_actions (
    id              SERIAL PRIMARY KEY,
    admin_id        INTEGER REFERENCES users(id) ON DELETE SET NULL,
    target_user_id  INTEGER NOT NULL,
    action          VARCHAR(20) NOT NULL,
    reason          TEXT,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_admin_actions_action
        CHECK (action IN ('block', 'unblock', 'delete'))
);

-- Список действий администратора и история по конкретному пользователю.
CREATE INDEX IF NOT EXISTS ix_admin_actions_admin_id
    ON admin_actions (admin_id);
CREATE INDEX IF NOT EXISTS ix_admin_actions_target_user_id
    ON admin_actions (target_user_id);

COMMIT;

-- ============================================================================
-- Проверка после COMMIT (выполните отдельно, вне транзакции):
--
--   SELECT column_name, data_type, is_nullable, column_default
--     FROM information_schema.columns
--    WHERE table_name = 'users' AND column_name = 'is_active';
--   -- ожидается: is_active | boolean | NO | true
--
--   SELECT column_name, data_type, is_nullable
--     FROM information_schema.columns
--    WHERE table_name = 'admin_actions'
--    ORDER BY ordinal_position;
--   -- ожидается 6 колонок: id, admin_id, target_user_id, action, reason,
--   -- created_at
--
--   SELECT count(*) FROM users WHERE is_active = FALSE;
--   -- сразу после миграции: 0 (блокировки появятся при работе нового кода)
--
--   SELECT count(*) FROM admin_actions;
--   -- сразу после миграции: 0
--
-- Откат (только после откачки API на предыдущую версию!):
--   BEGIN;
--   DROP TABLE IF EXISTS admin_actions;
--   ALTER TABLE users DROP COLUMN IF EXISTS is_active;
--   COMMIT;
-- ============================================================================
