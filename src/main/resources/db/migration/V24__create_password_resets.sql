-- One pending password-reset challenge per account; same shape as email_verifications.
CREATE TABLE password_resets (
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    code_hash VARCHAR(64) NOT NULL,
    sent_at TIMESTAMP WITH TIME ZONE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT ck_password_reset_hash CHECK (btrim(code_hash) <> ''),
    CONSTRAINT ck_password_reset_attempts CHECK (failed_attempts >= 0),
    CONSTRAINT ck_password_reset_expiry CHECK (expires_at > sent_at)
);
