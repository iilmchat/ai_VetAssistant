-- ============================================================================
-- VetAssistant v1.14.2 - связь записей на приём с карточками питомцев (T-173)
--
-- Назначение: добавить `appointments.patient_id` и индекс. Существующие
-- записи остаются с NULL и не теряются; новые book_appointment создаются
-- только после проверки/создания карточки питомца.
--
-- Применение (из корня /srv/vetassistant):
--   docker compose -f docker-compose.edge.yml exec -T db \
--     sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' \
--     < scripts/migrations/2026-11-17_appointments_patient.sql
--
-- Проверка:
--   \d appointments
--   SELECT count(*) FROM appointments WHERE patient_id IS NULL;
--
-- Идемпотентность: повторный запуск не падает (IF NOT EXISTS).
-- ============================================================================

BEGIN;

SET lock_timeout = '5s';

ALTER TABLE appointments
    ADD COLUMN IF NOT EXISTS patient_id INTEGER
    REFERENCES patients(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_appointments_patient_id
    ON appointments (patient_id);

COMMIT;
