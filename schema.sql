CREATE TABLE IF NOT EXISTS admins (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(80) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    recovery_email VARCHAR(255),
    recovery_phone VARCHAR(30),
    session_version INTEGER NOT NULL DEFAULT 1,
    tracker_id UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE admins ADD COLUMN IF NOT EXISTS recovery_email VARCHAR(255);
ALTER TABLE admins ADD COLUMN IF NOT EXISTS recovery_phone VARCHAR(30);
ALTER TABLE admins ADD COLUMN IF NOT EXISTS session_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE admins ADD COLUMN IF NOT EXISTS tracker_id UUID DEFAULT gen_random_uuid();
UPDATE admins SET tracker_id = gen_random_uuid() WHERE tracker_id IS NULL;
ALTER TABLE admins ALTER COLUMN tracker_id SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS admins_tracker_id_idx ON admins (tracker_id);

CREATE TABLE IF NOT EXISTS password_reset_codes (
    id BIGSERIAL PRIMARY KEY,
    admin_id BIGINT NOT NULL REFERENCES admins(id) ON DELETE CASCADE,
    code_hash TEXT NOT NULL,
    method VARCHAR(10) NOT NULL CHECK (method IN ('email', 'sms')),
    expires_at TIMESTAMPTZ NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    verified_at TIMESTAMPTZ,
    used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS password_reset_admin_created_idx
    ON password_reset_codes (admin_id, created_at DESC);

CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGSERIAL PRIMARY KEY,
    actor_admin_id BIGINT REFERENCES admins(id) ON DELETE SET NULL,
    action VARCHAR(40) NOT NULL,
    entity_type VARCHAR(40) NOT NULL,
    entity_id BIGINT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS audit_logs_created_idx ON audit_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS audit_logs_entity_idx ON audit_logs (entity_type, entity_id, created_at DESC);

CREATE TABLE IF NOT EXISTS students (
    id BIGSERIAL PRIMARY KEY,
    student_number VARCHAR(40) UNIQUE NOT NULL,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    email VARCHAR(255),
    attendance NUMERIC(5,2) NOT NULL CHECK (attendance >= 0 AND attendance <= 100),
    programming NUMERIC(5,2) NOT NULL CHECK (programming >= 0 AND programming <= 100),
    database NUMERIC(5,2) NOT NULL CHECK (database >= 0 AND database <= 100),
    mathematics NUMERIC(5,2) NOT NULL CHECK (mathematics >= 0 AND mathematics <= 100),
    networking NUMERIC(5,2) NOT NULL CHECK (networking >= 0 AND networking <= 100),
    web_development NUMERIC(5,2) NOT NULL CHECK (web_development >= 0 AND web_development <= 100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS students_name_idx ON students (last_name, first_name);
