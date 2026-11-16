-- ============================================================================
-- VetAssistant v1.14.0 - память и карточки пациентов (T-160.2)
--
-- Назначение: создать таблицы `patients` (карточки питомцев) и `episodes`
-- (краткие выжимки эпизодов для памяти ассистента) с векторными
-- эмбеддингами pgvector (384 измерения) и HNSW-индексом.
--
-- ТРЕБОВАНИЕ К БД: PostgreSQL 16 с расширением pgvector >= 0.5.
-- В образе `postgres:16-alpine` расширения НЕТ. Перед применением
-- переведите сервис `db` на образ `pgvector/pgvector:pg16` (тот же major
-- PostgreSQL 16, существующий volume `postgres_data` совместим).
-- Пример для edge-стека на /srv/vetassistant:
--
--   1) Бэкап:
--      docker compose -f docker-compose.edge.yml exec -T db \
--        sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' \
--        > /srv/vetassistant/backups/pre-v1.14.0-$(date +%F).sql
--
--   2) В docker-compose.edge.yml заменить:
--        image: postgres:16-alpine
--      на:
--        image: pgvector/pgvector:pg16
--
--   3) Перезапустить БД (API можно остановить, чтобы не было записи):
--      docker compose -f docker-compose.edge.yml stop api db
--      docker compose -f docker-compose.edge.yml up -d db
--
--   4) Применить миграцию (из корня /srv/vetassistant):
--      docker compose -f docker-compose.edge.yml exec -T db \
--        sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
--               -v ON_ERROR_STOP=1' \
--        < scripts/migrations/2026-11-16_patients.sql
--
--   5) Поднять API:
--      docker compose -f docker-compose.edge.yml up -d api
--
-- Проверка после применения:
--   \dx vector
--   \d patients
--   \d episodes
--   SELECT to_regclass('public.patients'), to_regclass('public.episodes');
--   SELECT format_type(atttypid, atttypmod) AS embedding_type
--     FROM pg_attribute
--    WHERE attrelid = 'public.episodes'::regclass AND attname = 'embedding';
-- Ожидается: vector, обе таблицы существуют, embedding_type = vector(384).
--
-- Откат (удаляет все карточки и эпизоды; расширение vector не трогаем,
-- оно может использоваться другими таблицами):
--   BEGIN;
--   DROP TABLE IF EXISTS episodes;
--   DROP TABLE IF EXISTS patients;
--   COMMIT;
--
-- Приватность (152-ФЗ): в `episodes.content` хранится только краткая
-- выжимка (<= 500 символов), без полных диалогов и контактных данных.
-- Удаление пользователя каскадно удаляет его пациентов и эпизоды.
-- Retention 180 дней - задача T-166.
--
-- Идемпотентность: повторный запуск не падает (IF NOT EXISTS + проверки).
-- Время выполнения: секунды на пустой таблице; HNSW-индекс строится
-- на существующих эпизодах (на старте их нет).
-- ============================================================================

BEGIN;

-- Не ждём вечно блокировки на живой БД: если кто-то держит таблицу,
-- миграция упадёт и её можно безопасно перезапустить.
SET lock_timeout = '5s';

-- 0. Расширение pgvector -------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS vector;

-- 1. patients ----------------------------------------------------------------
-- Карточка питомца принадлежит пользователю. Все поля, кроме имени и вида,
-- необязательны: карточку можно дозаполнять через PATCH.
CREATE TABLE IF NOT EXISTS patients (
    id                  SERIAL PRIMARY KEY,
    user_id             INTEGER NOT NULL
                        REFERENCES users(id) ON DELETE CASCADE,
    name                VARCHAR(120) NOT NULL,
    species             VARCHAR(16) NOT NULL,
    breed               VARCHAR(120),
    birth_date          DATE,
    weight              NUMERIC(6, 2),
    known_allergies     TEXT,
    chronic_conditions  TEXT,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_patients_species
        CHECK (species IN ('dog', 'cat')),
    CONSTRAINT ck_patients_name_not_blank
        CHECK (length(btrim(name)) > 0),
    CONSTRAINT ck_patients_weight_positive
        CHECK (weight IS NULL OR weight > 0),
    CONSTRAINT ck_patients_birth_date_not_future
        CHECK (birth_date IS NULL OR birth_date <= CURRENT_DATE)
);

CREATE INDEX IF NOT EXISTS ix_patients_user_id
    ON patients (user_id);

-- 2. episodes ----------------------------------------------------------------
-- Эпизод памяти: краткая выжимка обсуждения/записи/напоминания.
-- `embedding` заполняется той же моделью, что RAG:
-- sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 (384).
-- NULL допустим: при недоступности модели эпизод сохраняется без вектора
-- и участвует только в хронологическом контексте.
CREATE TABLE IF NOT EXISTS episodes (
    id          BIGSERIAL PRIMARY KEY,
    patient_id  INTEGER NOT NULL
                REFERENCES patients(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,
    type        VARCHAR(16) NOT NULL,
    content     TEXT NOT NULL,
    embedding   vector(384),
    created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_episodes_type
        CHECK (type IN ('chat', 'appointment', 'reminder', 'manual')),
    CONSTRAINT ck_episodes_content_not_blank
        CHECK (length(btrim(content)) > 0),
    CONSTRAINT ck_episodes_content_length
        CHECK (length(content) <= 500)
);

CREATE INDEX IF NOT EXISTS ix_episodes_patient_created
    ON episodes (patient_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_episodes_user_id
    ON episodes (user_id);

-- HNSW для косинусного поиска. Параметры по умолчанию pgvector:
-- m = 16, ef_construction = 64; для сотен/тысяч эпизодов достаточно.
CREATE INDEX IF NOT EXISTS ix_episodes_embedding_hnsw
    ON episodes USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- 3. Проверки ----------------------------------------------------------------
-- Явно падаем, если расширение/таблицы/тип/индекс не создались, чтобы
-- миграция не завершилась «успешно» в неполном состоянии.
DO $$
DECLARE
    embedding_type TEXT;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        RAISE EXCEPTION 'pgvector не установлен: extension "vector" отсутствует';
    END IF;

    IF to_regclass('public.patients') IS NULL THEN
        RAISE EXCEPTION 'таблица patients не создана';
    END IF;

    IF to_regclass('public.episodes') IS NULL THEN
        RAISE EXCEPTION 'таблица episodes не создана';
    END IF;

    SELECT format_type(a.atttypid, a.atttypmod)
      INTO embedding_type
      FROM pg_attribute AS a
     WHERE a.attrelid = 'public.episodes'::regclass
       AND a.attname = 'embedding'
       AND NOT a.attisdropped;

    IF embedding_type IS DISTINCT FROM 'vector(384)' THEN
        RAISE EXCEPTION
            'episodes.embedding имеет тип %, ожидался vector(384)',
            embedding_type;
    END IF;

    IF to_regclass('public.ix_episodes_embedding_hnsw') IS NULL THEN
        RAISE EXCEPTION 'HNSW-индекс ix_episodes_embedding_hnsw не создан';
    END IF;
END
$$;

COMMIT;
