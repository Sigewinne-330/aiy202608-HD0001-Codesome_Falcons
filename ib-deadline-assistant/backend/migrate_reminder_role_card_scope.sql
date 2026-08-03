USE ib_assistant;

ALTER TABLE reminder_role_cards
    ADD COLUMN IF NOT EXISTS scope VARCHAR(20) NOT NULL DEFAULT 'global'
    AFTER extensions;
