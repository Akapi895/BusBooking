package com.example.busbooking.data.adapter;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDateTime;
import java.util.Optional;

/** Pending "your trip was cancelled" emails, stored as notice_due_at on the refunded bookings. */
@Repository
public class TripCancellationNotices {
    static final int MAX_ATTEMPTS = 8;
    // Also the retry delay: a claimed notice that is not marked sent becomes due again after the lease.
    static final Duration LEASE = Duration.ofMinutes(5);
    private final JdbcTemplate jdbc;

    public TripCancellationNotices(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public Optional<Notice> claim(Instant now) {
        return jdbc.query("""
                WITH due AS (
                    SELECT id FROM bookings
                     WHERE notice_due_at <= ? AND notice_attempts < ?
                     ORDER BY notice_due_at, id LIMIT 1 FOR UPDATE SKIP LOCKED
                )
                UPDATE bookings b SET notice_due_at = ?, notice_attempts = b.notice_attempts + 1
                  FROM due, users u, trips t, routes r, locations o, locations d
                 WHERE b.id = due.id AND u.id = b.user_id AND t.id = b.trip_id
                   AND r.id = t.route_id AND o.id = r.origin_id AND d.id = r.destination_id
                RETURNING b.id, u.email, b.booking_code, b.passenger_name, o.name, d.name,
                          t.departure_time, b.total_amount
                """, (row, index) -> new Notice(row.getLong(1), row.getString(2), row.getString(3),
                        row.getString(4), row.getString(5), row.getString(6),
                        row.getTimestamp(7).toLocalDateTime(), row.getBigDecimal(8)),
                Timestamp.from(now), MAX_ATTEMPTS, Timestamp.from(now.plus(LEASE))).stream().findFirst();
    }

    public void sent(long bookingId) {
        jdbc.update("UPDATE bookings SET notice_due_at = NULL WHERE id = ?", bookingId);
    }

    public record Notice(long bookingId, String email, String bookingCode, String passengerName,
                         String origin, String destination, LocalDateTime departure, BigDecimal refund) {
        @Override public String toString() { return "Trip cancellation notice " + bookingId; }
    }
}
