package com.example.busbooking.business.service;

import com.example.busbooking.business.port.notification.PasswordResetSender;
import com.example.busbooking.business.port.repository.EmailVerificationRepository.ResendResult;
import com.example.busbooking.business.port.repository.PasswordResetRepository;
import com.example.busbooking.business.port.security.PasswordHasher;
import com.example.busbooking.business.port.security.VerificationCodeProvider;
import com.example.busbooking.domain.exception.InvalidVerificationCodeException;
import com.example.busbooking.domain.exception.VerificationRateLimitException;
import java.time.Clock;
import java.time.Instant;

public class PasswordResetService {
    private final PasswordResetRepository repository;
    private final VerificationCodeProvider codes;
    private final PasswordResetSender sender;
    private final PasswordHasher passwords;
    private final Clock clock;

    public PasswordResetService(PasswordResetRepository repository, VerificationCodeProvider codes,
                                PasswordResetSender sender, PasswordHasher passwords, Clock clock) {
        this.repository = repository;
        this.codes = codes;
        this.sender = sender;
        this.passwords = passwords;
        this.clock = clock;
    }

    public void request(String rawEmail) {
        String email = AuthInputPolicy.email(rawEmail);
        String code = codes.generate();
        Instant now = clock.instant();
        Instant expiresAt = now.plus(EmailVerificationService.CODE_TTL);
        var result = repository.issue(email, codes.digest(email, code), now, expiresAt,
                EmailVerificationService.RESEND_COOLDOWN);
        if (result == ResendResult.TOO_SOON) { throw new VerificationRateLimitException(); }
        // shortcut: sent synchronously after the challenge commits, not via the outbox; move to the outbox if SMTP is flaky.
        if (result == ResendResult.REPLACED) { sender.send(email, code, expiresAt); }
        // Unknown, unverified and inactive accounts get the same outward response.
    }

    public void reset(String rawEmail, String code, String newPassword) {
        if (code == null || !code.matches("[0-9]{6}")) { throw new InvalidVerificationCodeException(); }
        String email = AuthInputPolicy.email(rawEmail);
        AuthInputPolicy.registrationPassword(newPassword);
        if (!repository.reset(email, codes.digest(email, code), passwords.hash(newPassword), clock,
                EmailVerificationService.MAX_ATTEMPTS)) {
            throw new InvalidVerificationCodeException();
        }
    }
}
