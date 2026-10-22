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
    tracker_id UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    owner_admin_id BIGINT REFERENCES admins(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS students_name_idx ON students (last_name, first_name);


ALTER TABLE students ADD COLUMN IF NOT EXISTS tracker_id UUID DEFAULT gen_random_uuid();
UPDATE students SET tracker_id = gen_random_uuid() WHERE tracker_id IS NULL;
ALTER TABLE students ALTER COLUMN tracker_id SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS students_tracker_id_idx ON students (tracker_id);

CREATE TABLE IF NOT EXISTS sign_in_logs (
    id BIGSERIAL PRIMARY KEY,
    account_type VARCHAR(10) NOT NULL CHECK (account_type IN ('admin', 'student')),
    account_id BIGINT NOT NULL,
    account_identifier VARCHAR(100) NOT NULL,
    account_name VARCHAR(205) NOT NULL,
    tracker_id UUID NOT NULL,
    signed_in_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS sign_in_logs_signed_in_idx ON sign_in_logs (signed_in_at DESC);
CREATE INDEX IF NOT EXISTS sign_in_logs_account_idx ON sign_in_logs (account_type, account_id, signed_in_at DESC);

CREATE TABLE IF NOT EXISTS student_accounts (
    id BIGSERIAL PRIMARY KEY,
    student_id BIGINT NOT NULL UNIQUE REFERENCES students(id) ON DELETE CASCADE,
    password_hash TEXT NOT NULL,
    status VARCHAR(10) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TIMESTAMPTZ,
    reviewed_by_admin_id BIGINT REFERENCES admins(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS student_accounts_status_idx ON student_accounts (status, created_at DESC);

-- Subject-based grading and editable term records.
CREATE TABLE IF NOT EXISTS subjects (
    id BIGSERIAL PRIMARY KEY,
    subject_code VARCHAR(30) NOT NULL UNIQUE,
    subject_name VARCHAR(150) NOT NULL UNIQUE,
    units NUMERIC(4,1) NOT NULL DEFAULT 3 CHECK (units > 0 AND units <= 30),
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO subjects (subject_code, subject_name, units) VALUES
    ('PROG', 'Programming', 3),
    ('DB', 'Database', 3),
    ('MATH', 'Mathematics', 3),
    ('NET', 'Networking', 3),
    ('WEB', 'Web Development', 3)
ON CONFLICT (subject_code) DO NOTHING;

CREATE TABLE IF NOT EXISTS student_subjects (
    id BIGSERIAL PRIMARY KEY,
    student_id BIGINT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    subject_id BIGINT NOT NULL REFERENCES subjects(id) ON DELETE RESTRICT,
    academic_year VARCHAR(20) NOT NULL DEFAULT '2026-2027',
    semester VARCHAR(20) NOT NULL DEFAULT '1st Semester',
    enrolled_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (student_id, subject_id, academic_year, semester)
);
CREATE INDEX IF NOT EXISTS student_subjects_student_idx ON student_subjects (student_id, academic_year, semester);
CREATE INDEX IF NOT EXISTS student_subjects_subject_idx ON student_subjects (subject_id, academic_year, semester);

CREATE TABLE IF NOT EXISTS grade_records (
    id BIGSERIAL PRIMARY KEY,
    student_subject_id BIGINT NOT NULL REFERENCES student_subjects(id) ON DELETE CASCADE,
    term VARCHAR(10) NOT NULL CHECK (term IN ('Midterms', 'Finals')),
    percentage NUMERIC(5,2) NOT NULL CHECK (percentage >= 0 AND percentage <= 100),
    recorded_by_admin_id BIGINT REFERENCES admins(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (student_subject_id, term)
);
CREATE INDEX IF NOT EXISTS grade_records_enrollment_idx ON grade_records (student_subject_id, term);

CREATE TABLE IF NOT EXISTS grade_record_history (
    id BIGSERIAL PRIMARY KEY,
    student_subject_id BIGINT NOT NULL REFERENCES student_subjects(id) ON DELETE CASCADE,
    term VARCHAR(10) NOT NULL CHECK (term IN ('Midterms', 'Finals')),
    action VARCHAR(10) NOT NULL CHECK (action IN ('created', 'updated', 'deleted')),
    previous_percentage NUMERIC(5,2),
    new_percentage NUMERIC(5,2),
    actor_admin_id BIGINT REFERENCES admins(id) ON DELETE SET NULL,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS grade_record_history_enrollment_idx ON grade_record_history (student_subject_id, changed_at DESC);

CREATE TABLE IF NOT EXISTS grading_policies (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    dean_list_gwa_max NUMERIC(3,2) NOT NULL DEFAULT 1.75 CHECK (dean_list_gwa_max > 0 AND dean_list_gwa_max <= 5),
    max_subject_gwa NUMERIC(3,2) NOT NULL DEFAULT 2.50 CHECK (max_subject_gwa > 0 AND max_subject_gwa <= 5),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO grading_policies (id, dean_list_gwa_max, max_subject_gwa)
VALUES (1, 1.75, 2.50) ON CONFLICT (id) DO NOTHING;


-- Per-administrator student trackers. Existing records remain unassigned (owner_admin_id IS NULL)
-- and are preserved separately; new records belong to the administrator who created them.
ALTER TABLE students ADD COLUMN IF NOT EXISTS owner_admin_id BIGINT REFERENCES admins(id) ON DELETE SET NULL;

DO $$
DECLARE
    unique_constraint_name TEXT;
BEGIN
    SELECT c.conname INTO unique_constraint_name
    FROM pg_constraint c
    WHERE c.conrelid = 'students'::regclass
      AND c.contype = 'u'
      AND pg_get_constraintdef(c.oid) = 'UNIQUE (student_number)'
    LIMIT 1;
    IF unique_constraint_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE students DROP CONSTRAINT %I', unique_constraint_name);
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS students_owner_number_idx
    ON students (owner_admin_id, student_number)
    WHERE owner_admin_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS students_owner_name_idx
    ON students (owner_admin_id, last_name, first_name);
