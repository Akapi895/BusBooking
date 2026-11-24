package com.example.busbooking.business.port.repository;

import java.time.Instant;

public interface BookingIdempotencyRepository {
    record Replay(String requestHash, long bookingId) {}

    // Returns null when the current transaction owns the key.
    Replay reserve(long userId, String key, String hash, Instant now);
    void complete(long userId, String key, long bookingId);
    void deleteExpired(Instant now);
}
