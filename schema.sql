CREATE TABLE IF NOT EXISTS admins (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(80) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

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

CREATE TABLE IF NOT EXISTS student_accounts (
    id BIGSERIAL PRIMARY KEY,
    student_id BIGINT NOT NULL UNIQUE REFERENCES students(id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE student_accounts ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS student_accounts_email_idx ON student_accounts (LOWER(email));

ALTER TABLE student_accounts ADD COLUMN IF NOT EXISTS privacy_notice_version VARCHAR(20);
ALTER TABLE student_accounts ADD COLUMN IF NOT EXISTS privacy_notice_acknowledged_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS auth_login_attempts (
    identifier_hash CHAR(64) PRIMARY KEY,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    first_attempt_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    locked_until TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS auth_login_attempts_first_attempt_idx ON auth_login_attempts (first_attempt_at);
