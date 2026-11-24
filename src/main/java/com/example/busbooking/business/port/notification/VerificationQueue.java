package com.example.busbooking.business.port.notification;

import com.example.busbooking.business.port.repository.EmailVerificationRepository.ResendResult;
import com.example.busbooking.domain.model.User;

import java.time.Duration;
import java.time.Instant;

public interface VerificationQueue {
    User register(User user, String code, String digest, Instant now, Instant expiry);
    ResendResult resend(String email, String code, String digest, Instant now, Instant expiry, Duration cooldown);
}
