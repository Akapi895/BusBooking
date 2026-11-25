package com.example.busbooking.business.port.notification;

import java.time.Instant;

public interface PasswordResetSender {
    void send(String email, String code, Instant expiresAt);
}
