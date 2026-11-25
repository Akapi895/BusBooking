-- Cancelling a trip moves its confirmed bookings to REFUND_PENDING; an admin marks them REFUNDED
-- after paying the customer back outside the system.
ALTER TABLE bookings DROP CONSTRAINT ck_bookings_status;
ALTER TABLE bookings ADD CONSTRAINT ck_bookings_status
    CHECK (status IN ('CONFIRMED', 'CANCELLED', 'REFUND_PENDING', 'REFUNDED'));

ALTER TABLE bookings
    ADD COLUMN refunded_at TIMESTAMPTZ,
    -- Non-null while the cancellation email still has to be sent; also the next attempt time.
    ADD COLUMN notice_due_at TIMESTAMPTZ,
    ADD COLUMN notice_attempts INTEGER NOT NULL DEFAULT 0;

CREATE INDEX idx_bookings_notice_due ON bookings (notice_due_at) WHERE notice_due_at IS NOT NULL;
