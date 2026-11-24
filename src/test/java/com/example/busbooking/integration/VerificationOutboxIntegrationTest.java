package com.example.busbooking.integration;

import com.example.busbooking.business.command.RegisterCommand;
import com.example.busbooking.business.command.VerifyEmailCommand;
import com.example.busbooking.business.service.AuthService;
import com.example.busbooking.business.service.EmailVerificationService;
import com.example.busbooking.business.port.notification.EmailVerificationSender;
import com.example.busbooking.data.adapter.VerificationOutbox;
import com.example.busbooking.domain.exception.EmailDeliveryException;
import com.example.busbooking.notification.VerificationOutboxWorker;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;

import java.time.Instant;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@SpringBootTest(properties = {
        "auth.email-outbox.enabled=true",
        "auth.email-outbox.secret=YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXowMTIzNDU=",
        "auth.email-outbox.poll-ms=86400000"
})
@ActiveProfiles("test")
class VerificationOutboxIntegrationTest {
    @Autowired AuthService auth;
    @Autowired EmailVerificationService verification;
    @Autowired VerificationOutbox outbox;
    @Autowired VerificationOutboxWorker worker;
    @Autowired JdbcTemplate jdbc;
    @MockitoBean EmailVerificationSender sender;

    final String email = UUID.randomUUID() + "@outbox.example";

    @AfterEach
    void clean() {
        jdbc.update("DELETE FROM users WHERE email = ?", email);
    }

    @Test
    void failedResendLeavesPreviouslyDeliveredCodeUsable() {
        var account = auth.register(new RegisterCommand("Outbox Test", email, "ExamplePass123", "0901234567"));
        var code = new AtomicReference<String>();
        doAnswer(call -> { code.set(call.getArgument(1)); return null; })
                .when(sender).send(eq(email), anyString(), any());
        worker.dispatch();
        assertThat(code.get()).matches("[0-9]{6}");

        jdbc.update("UPDATE verification_outbox SET created_at = created_at - interval '61 seconds' WHERE user_id = ?", account.id());
        jdbc.update("UPDATE email_verifications SET sent_at = sent_at - interval '61 seconds' WHERE user_id = ?", account.id());
        doThrow(new EmailDeliveryException()).when(sender).send(eq(email), anyString(), any());
        verification.resend(email);
        worker.dispatch();
        assertThat(jdbc.queryForObject("""
                SELECT attempts FROM verification_outbox WHERE user_id = ? AND finished_at IS NULL
                """, Integer.class, account.id())).isEqualTo(1);
        verification.verify(new VerifyEmailCommand(email, code.get()));
        assertThat(jdbc.queryForObject("SELECT email_verified FROM users WHERE id = ?", Boolean.class, account.id())).isTrue();
    }

    @Test
    void workCanBeClaimedAgainAfterItsLeaseExpires() {
        var account = auth.register(new RegisterCommand("Outbox Test", email, "ExamplePass123", "0901234567"));
        var now = Instant.now();
        var first = outbox.claim(now).orElseThrow();
        assertThat(first.userId()).isEqualTo(account.id());
        assertThat(outbox.claim(now.plusSeconds(30))).isEmpty();

        var retried = outbox.claim(now.plusSeconds(61)).orElseThrow();
        assertThat(retried.id()).isEqualTo(first.id());
        assertThat(retried.attempt()).isEqualTo(first.attempt() + 1);
        assertThat(retried.payload()).hasSizeGreaterThan(6);
    }
}
