package com.example.busbooking.data.adapter;

import com.example.busbooking.business.port.repository.BookingIdempotencyRepository;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;

@Repository
public class BookingIdempotencyRepositoryAdapter implements BookingIdempotencyRepository {
    private final JdbcTemplate jdbc;

    public BookingIdempotencyRepositoryAdapter(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public Replay reserve(long userId, String key, String hash, Instant now) {
        int written = jdbc.update("""
                INSERT INTO booking_idempotency (user_id, request_key, request_hash, expires_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (user_id, request_key) DO UPDATE
                  SET request_hash = EXCLUDED.request_hash, expires_at = EXCLUDED.expires_at, booking_id = NULL
                WHERE booking_idempotency.expires_at <= ?
                """, userId, key, hash, Timestamp.from(now.plus(Duration.ofHours(24))), Timestamp.from(now));
        if (written != 0) return null;
        return jdbc.queryForObject("""
                SELECT request_hash, booking_id FROM booking_idempotency WHERE user_id = ? AND request_key = ?
                """, (row, index) -> new Replay(row.getString(1), row.getLong(2)), userId, key);
    }

    @Override
    public void complete(long userId, String key, long bookingId) {
        jdbc.update("UPDATE booking_idempotency SET booking_id = ? WHERE user_id = ? AND request_key = ?",
                bookingId, userId, key);
    }

    @Override
    public void deleteExpired(Instant now) {
        jdbc.update("""
                DELETE FROM booking_idempotency WHERE (user_id, request_key) IN (
                    SELECT user_id, request_key FROM booking_idempotency
                    WHERE expires_at <= ? LIMIT 1000 FOR UPDATE SKIP LOCKED
                )
                """, Timestamp.from(now));
    }
}
