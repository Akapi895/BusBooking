package com.example.busbooking.notification;

import com.example.busbooking.business.port.notification.EmailVerificationSender;
import com.example.busbooking.data.adapter.VerificationOutbox;
import com.example.busbooking.domain.exception.EmailDeliveryException;
import com.example.busbooking.security.VerificationPayloadCipher;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Clock;

@Component
@ConditionalOnProperty(name = "auth.email-outbox.enabled", havingValue = "true", matchIfMissing = true)
public class VerificationOutboxWorker {
    private static final Logger LOG = LoggerFactory.getLogger(VerificationOutboxWorker.class);
    private final VerificationOutbox outbox;
    private final VerificationPayloadCipher cipher;
    private final EmailVerificationSender sender;
    private final Clock clock;

    public VerificationOutboxWorker(VerificationOutbox outbox, VerificationPayloadCipher cipher,
                                    EmailVerificationSender sender, Clock clock) {
        this.outbox = outbox;
        this.cipher = cipher;
        this.sender = sender;
        this.clock = clock;
    }

    @Scheduled(fixedDelayString = "${auth.email-outbox.poll-ms:1000}")
    public void dispatch() {
        for (int i = 0; i < 10; i++) {
            var next = outbox.claim(clock.instant());
            if (next.isEmpty()) return;
            var delivery = next.get();
            try {
                sender.send(delivery.email(), cipher.decrypt(delivery.payload(), delivery.digest()), delivery.expiry());
            } catch (EmailDeliveryException | IllegalStateException failure) {
                LOG.warn("Verification delivery {} failed on attempt {}", delivery.id(), delivery.attempt());
                outbox.retry(delivery, clock.instant());
                continue;
            }
            outbox.delivered(delivery, clock.instant());
        }
    }

    @Scheduled(fixedDelay = 60_000)
    public void cleanUp() {
        outbox.cleanUp(clock.instant());
    }
}
