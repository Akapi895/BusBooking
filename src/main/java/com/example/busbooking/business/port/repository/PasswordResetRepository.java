package com.example.busbooking.business.port.repository;

import com.example.busbooking.business.port.repository.EmailVerificationRepository.ResendResult;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;

public interface PasswordResetRepository {
    /** REPLACED only for an active, verified account outside the cooldown. */
    ResendResult issue(String email, String digest, Instant now, Instant expiresAt, Duration cooldown);
    /** On a matching code, stores the hash, revokes earlier tokens and consumes the code. */
    boolean reset(String email, String digest, String passwordHash, Clock clock, int maxAttempts);
}
