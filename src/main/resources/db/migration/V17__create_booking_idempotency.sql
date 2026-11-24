CREATE TABLE booking_idempotency (
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    request_key VARCHAR(128) NOT NULL,
    request_hash VARCHAR(64) NOT NULL,
    booking_id BIGINT REFERENCES bookings(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (user_id, request_key)
);
CREATE INDEX idx_booking_idempotency_expiry ON booking_idempotency (expires_at);
