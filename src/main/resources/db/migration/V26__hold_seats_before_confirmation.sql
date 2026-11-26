-- A new booking holds its seats (HELD) until the customer confirms it. An unconfirmed hold
-- lapses at hold_expires_at: it becomes EXPIRED and its seats go back to the trip.
ALTER TABLE bookings DROP CONSTRAINT ck_bookings_status;
ALTER TABLE bookings ADD CONSTRAINT ck_bookings_status
    CHECK (status IN ('HELD', 'CONFIRMED', 'EXPIRED', 'CANCELLED', 'REFUND_PENDING', 'REFUNDED'));

ALTER TABLE bookings ADD COLUMN hold_expires_at TIMESTAMP;
ALTER TABLE bookings ADD CONSTRAINT ck_bookings_hold_expiry
    CHECK (status <> 'HELD' OR hold_expires_at IS NOT NULL);

CREATE INDEX idx_bookings_hold_expiry ON bookings (hold_expires_at) WHERE status = 'HELD';
