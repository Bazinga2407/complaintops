CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    provider_subject TEXT UNIQUE,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT,
    role VARCHAR(20) NOT NULL DEFAULT 'operator'
        CHECK (role IN ('operator', 'reviewer', 'admin')),
    status VARCHAR(20) NOT NULL DEFAULT 'invited'
        CHECK (status IN ('invited', 'active', 'disabled')),
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS users_email_lower_idx ON users (LOWER(email));

ALTER TABLE review_actions
    ADD COLUMN IF NOT EXISTS reviewer_user_id UUID REFERENCES users(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS review_actions_reviewer_user_idx
    ON review_actions (reviewer_user_id);
