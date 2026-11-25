package com.example.busbooking.data.adapter;

import com.example.busbooking.business.port.repository.EmailVerificationRepository.ResendResult;
import com.example.busbooking.business.port.repository.PasswordResetRepository;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;

@Component
public class PasswordResetRepositoryAdapter implements PasswordResetRepository {
    private final JdbcTemplate jdbc;

    public PasswordResetRepositoryAdapter(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    @Override
    @Transactional
    public ResendResult issue(String email, String digest, Instant now, Instant expiresAt, Duration cooldown) {
        Long userId = lockEligible(email);
        if (userId == null) { return ResendResult.IGNORED; }
        var sentAt = jdbc.query("SELECT sent_at FROM password_resets WHERE user_id = ?",
                (row, index) -> row.getTimestamp("sent_at").toInstant(), userId);
        if (!sentAt.isEmpty() && now.isBefore(sentAt.getFirst().plus(cooldown))) { return ResendResult.TOO_SOON; }
        jdbc.update("""
                INSERT INTO password_resets(user_id, code_hash, sent_at, expires_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (user_id) DO UPDATE
                SET code_hash = EXCLUDED.code_hash, sent_at = EXCLUDED.sent_at,
                    expires_at = EXCLUDED.expires_at, failed_attempts = 0
                """, userId, digest, Timestamp.from(now), Timestamp.from(expiresAt));
        return ResendResult.REPLACED;
    }

    @Override
    @Transactional
    public boolean reset(String email, String digest, String passwordHash, Clock clock, int maxAttempts) {
        Long userId = lockEligible(email);
        if (userId == null) { return false; }
        var challenges = jdbc.query("SELECT code_hash, expires_at, failed_attempts FROM password_resets WHERE user_id = ?",
                (row, index) -> new Challenge(row.getString("code_hash"), row.getTimestamp("expires_at").toInstant(),
                        row.getInt("failed_attempts")), userId);
        if (challenges.isEmpty()) { return false; }
        Challenge challenge = challenges.getFirst();
        // Read the clock after the account lock, as email verification does.
        if (!clock.instant().isBefore(challenge.expiresAt()) || challenge.attempts() >= maxAttempts) { return false; }
        if (!MessageDigest.isEqual(digest.getBytes(StandardCharsets.US_ASCII),
                challenge.digest().getBytes(StandardCharsets.US_ASCII))) {
            jdbc.update("UPDATE password_resets SET failed_attempts = failed_attempts + 1 WHERE user_id = ?", userId);
            return false;
        }
        jdbc.update("UPDATE users SET password = ?, token_version = token_version + 1 WHERE id = ?", passwordHash, userId);
        jdbc.update("DELETE FROM password_resets WHERE user_id = ?", userId);
        return true;
    }

    private Long lockEligible(String email) {
        var ids = jdbc.query("""
                SELECT id FROM users WHERE email = ? AND status = 'ACTIVE' AND email_verified = TRUE FOR UPDATE
                """, (row, index) -> row.getLong("id"), email);
        return ids.isEmpty() ? null : ids.getFirst();
    }

    private record Challenge(String digest, Instant expiresAt, int attempts) {
        @Override public String toString() { return "Challenge[REDACTED]"; }
    }
}
