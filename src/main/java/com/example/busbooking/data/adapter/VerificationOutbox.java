package com.example.busbooking.data.adapter;

import com.example.busbooking.business.port.notification.VerificationQueue;
import com.example.busbooking.business.port.repository.EmailVerificationRepository;
import com.example.busbooking.business.port.repository.UserRepository;
import com.example.busbooking.domain.model.User;
import com.example.busbooking.security.VerificationPayloadCipher;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.util.Optional;

@Repository
@ConditionalOnProperty(name = "auth.email-outbox.enabled", havingValue = "true", matchIfMissing = true)
public class VerificationOutbox implements VerificationQueue {
    private final JdbcTemplate jdbc;
    private final UserRepository users;
    private final VerificationPayloadCipher cipher;

    public VerificationOutbox(JdbcTemplate jdbc, UserRepository users, VerificationPayloadCipher cipher) {
        this.jdbc = jdbc;
        this.users = users;
        this.cipher = cipher;
    }

    @Override
    @Transactional
    public User register(User user, String code, String digest, Instant now, Instant expiry) {
        User saved = users.save(user);
        enqueue(saved.getId(), code, digest, now, expiry);
        return saved;
    }

    @Override
    @Transactional
    public EmailVerificationRepository.ResendResult resend(String email, String code, String digest,
                                                           Instant now, Instant expiry, Duration cooldown) {
        var eligible = jdbc.query("""
                SELECT id FROM users WHERE email = ? AND status = 'ACTIVE' AND NOT email_verified FOR UPDATE
                """, (row, index) -> row.getLong(1), email);
        if (eligible.isEmpty()) return EmailVerificationRepository.ResendResult.IGNORED;
        long userId = eligible.getFirst();
        Boolean tooSoon = jdbc.queryForObject("""
                SELECT EXISTS (
                    SELECT 1 FROM verification_outbox WHERE user_id = ? AND created_at > ?
                    UNION ALL
                    SELECT 1 FROM email_verifications WHERE user_id = ? AND sent_at > ?
                )
                """, Boolean.class, userId, timestamp(now.minus(cooldown)), userId, timestamp(now.minus(cooldown)));
        if (Boolean.TRUE.equals(tooSoon)) return EmailVerificationRepository.ResendResult.TOO_SOON;
        jdbc.update("""
                UPDATE verification_outbox SET finished_at = ?, ciphertext = ''::bytea
                WHERE user_id = ? AND finished_at IS NULL
                """, timestamp(now), userId);
        enqueue(userId, code, digest, now, expiry);
        return EmailVerificationRepository.ResendResult.REPLACED;
    }

    private void enqueue(long userId, String code, String digest, Instant now, Instant expiry) {
        jdbc.update("""
                INSERT INTO verification_outbox
                    (user_id, code_hash, expires_at, ciphertext, created_at, next_attempt_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """, userId, digest, timestamp(expiry), cipher.encrypt(code, digest), timestamp(now), timestamp(now));
    }

    public Optional<Delivery> claim(Instant now) {
        return jdbc.query("""
                WITH due AS (
                    SELECT o.id FROM verification_outbox o JOIN users u ON u.id = o.user_id
                     WHERE o.finished_at IS NULL AND o.next_attempt_at <= ? AND o.expires_at > ?
                       AND (o.lease_until IS NULL OR o.lease_until <= ?) AND o.attempts < 8
                       AND u.status = 'ACTIVE' AND NOT u.email_verified
                     ORDER BY o.next_attempt_at, o.id LIMIT 1 FOR UPDATE OF o SKIP LOCKED
                )
                UPDATE verification_outbox o SET attempts = attempts + 1, lease_until = ?
                  FROM due, users u WHERE o.id = due.id AND u.id = o.user_id
                RETURNING o.id, o.user_id, u.email, o.code_hash, o.ciphertext, o.expires_at, o.attempts
                """, (row, index) -> new Delivery(row.getLong(1), row.getLong(2), row.getString(3),
                        row.getString(4), row.getBytes(5), row.getTimestamp(6).toInstant(), row.getInt(7)),
                timestamp(now), timestamp(now), timestamp(now), timestamp(now.plusSeconds(60))).stream().findFirst();
    }

    public void retry(Delivery delivery, Instant now) {
        long delay = Math.min(120, 5L << (delivery.attempt() - 1));
        jdbc.update("""
                UPDATE verification_outbox SET lease_until = NULL, next_attempt_at = ?
                 WHERE id = ? AND attempts = ? AND finished_at IS NULL
                """, timestamp(now.plusSeconds(delay)), delivery.id(), delivery.attempt());
    }

    @Transactional
    public void delivered(Delivery delivery, Instant now) {
        var eligible = jdbc.query("""
                SELECT id FROM users WHERE id = ? AND status = 'ACTIVE' AND NOT email_verified FOR UPDATE
                """, (row, index) -> row.getLong(1), delivery.userId());
        int updated = jdbc.update("""
                UPDATE verification_outbox SET finished_at = ?, ciphertext = ''::bytea, lease_until = NULL
                 WHERE id = ? AND attempts = ? AND finished_at IS NULL
                """, timestamp(now), delivery.id(), delivery.attempt());
        if (updated == 0 || eligible.isEmpty() || !now.isBefore(delivery.expiry())) return;
        jdbc.update("""
                INSERT INTO email_verifications (user_id, code_hash, expires_at, sent_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (user_id) DO UPDATE SET code_hash = EXCLUDED.code_hash,
                    expires_at = EXCLUDED.expires_at, sent_at = EXCLUDED.sent_at, failed_attempts = 0
                """, delivery.userId(), delivery.digest(), timestamp(delivery.expiry()), timestamp(now));
    }

    public void cleanUp(Instant now) {
        jdbc.update("""
                UPDATE verification_outbox SET finished_at = ?, ciphertext = ''::bytea, lease_until = NULL
                WHERE finished_at IS NULL AND (lease_until IS NULL OR lease_until <= ?)
                  AND (expires_at <= ? OR attempts >= 8 OR NOT EXISTS (
                      SELECT 1 FROM users WHERE id = user_id AND status = 'ACTIVE' AND NOT email_verified
                  ))
                """, timestamp(now), timestamp(now), timestamp(now));
        jdbc.update("DELETE FROM verification_outbox WHERE finished_at < ?", timestamp(now.minus(Duration.ofDays(1))));
    }

    private static Timestamp timestamp(Instant value) {
        return Timestamp.from(value);
    }

    public record Delivery(long id, long userId, String email, String digest, byte[] payload, Instant expiry, int attempt) {
        @Override public String toString() { return "Verification delivery " + id; }
    }
}
