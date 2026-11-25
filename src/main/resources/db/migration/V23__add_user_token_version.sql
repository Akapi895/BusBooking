-- Incremented on logout; access tokens carrying an older version are rejected.
ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD CONSTRAINT ck_users_token_version CHECK (token_version >= 0);
