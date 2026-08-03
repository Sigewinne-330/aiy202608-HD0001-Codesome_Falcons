-- Existing reminder_deliveries tables created before the crash-safety state
-- need this idempotent type widening. Fresh databases already use init_db.sql.
USE ib_assistant;

ALTER TABLE reminder_deliveries
    MODIFY COLUMN status
    ENUM('pending','attempting','delivered','retryable','failed','skipped')
    NOT NULL DEFAULT 'pending';

ALTER TABLE reminder_deliveries
    ADD COLUMN IF NOT EXISTS attempt_token VARCHAR(64) NULL AFTER attempt_count,
    ADD COLUMN IF NOT EXISTS attempt_started_at DATETIME NULL AFTER attempt_token;
