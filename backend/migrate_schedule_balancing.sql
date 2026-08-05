-- Additive scheduling migration for existing MySQL deployments.
-- Run after the application models have been deployed.  New tables are also
-- created by SQLAlchemy startup; this file is provided for operators who use
-- explicit SQL migrations.  No existing task/deadline rows are rewritten.

ALTER TABLE `task`
    ADD COLUMN `earliest_start_date` DATE NULL,
    ADD COLUMN `hard_deadline_date` DATE NULL,
    ADD COLUMN `energy_intensity` DECIMAL(3,2) NOT NULL DEFAULT 1.0,
    ADD COLUMN `effort_source` VARCHAR(20) NOT NULL DEFAULT 'default',
    ADD COLUMN `is_schedule_locked` BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN `schedule_version` INT NOT NULL DEFAULT 1,
    ADD COLUMN `deferral_count` INT NOT NULL DEFAULT 0,
    ADD COLUMN `schedule_kind` VARCHAR(50) NULL;

ALTER TABLE `sub_task`
    ADD COLUMN `estimated_hours` DECIMAL(5,1) NOT NULL DEFAULT 0,
    ADD COLUMN `earliest_start_date` DATE NULL,
    ADD COLUMN `hard_deadline_date` DATE NULL,
    ADD COLUMN `energy_intensity` DECIMAL(3,2) NOT NULL DEFAULT 1.0,
    ADD COLUMN `effort_source` VARCHAR(20) NOT NULL DEFAULT 'default',
    ADD COLUMN `is_schedule_locked` BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN `schedule_version` INT NOT NULL DEFAULT 1,
    ADD COLUMN `deferral_count` INT NOT NULL DEFAULT 0,
    ADD COLUMN `schedule_kind` VARCHAR(50) NULL;

ALTER TABLE `deadlines`
    ADD COLUMN `estimated_hours` DECIMAL(5,1) NULL,
    ADD COLUMN `energy_intensity` DECIMAL(3,2) NOT NULL DEFAULT 1.0,
    ADD COLUMN `effort_source` VARCHAR(20) NOT NULL DEFAULT 'default',
    ADD COLUMN `is_schedule_locked` BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN `schedule_version` INT NOT NULL DEFAULT 1,
    ADD COLUMN `schedule_kind` VARCHAR(50) NULL;

ALTER TABLE `schedule_interventions`
    ADD COLUMN `resolution_idempotency_key` VARCHAR(128) NULL;

-- The overload clarification state is longer than the original VARCHAR(20)
-- definition.  Keep the schema aligned with models/scheduling.py.
ALTER TABLE `schedule_interventions`
    MODIFY COLUMN `state` VARCHAR(32) NOT NULL;

-- New tables and indexes are emitted by Base.metadata.create_all.  If a
-- deployment uses only SQL, run the generated DDL from the current models.
