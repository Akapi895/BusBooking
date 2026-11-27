package com.example.busbooking.notification;

import com.example.busbooking.data.adapter.TripCancellationNotices;
import org.junit.jupiter.api.Test;
import org.springframework.mail.MailSendException;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;

import java.math.BigDecimal;
import java.time.*;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

class TripCancellationNoticeWorkerTest {
    private final TripCancellationNotices notices = mock(TripCancellationNotices.class);
    private final JavaMailSender mail = mock(JavaMailSender.class);
    private final Clock clock = Clock.fixed(Instant.parse("2026-01-01T00:00:00Z"), ZoneOffset.UTC);
    private final TripCancellationNoticeWorker worker =
            new TripCancellationNoticeWorker(notices, mail, "noreply@example.com", clock);
    private final TripCancellationNotices.Notice notice = new TripCancellationNotices.Notice(7L, "khach@example.com",
            "BK-1", "Nguyen Van A", "Ha Noi", "Hai Phong", LocalDateTime.of(2026, 1, 2, 8, 0), new BigDecimal("250000.00"));

    @Test
    void sendsNoticeWithRefundAndMarksItSent() {
        when(notices.claim(any())).thenReturn(Optional.of(notice), Optional.empty());
        worker.dispatch();
        var sent = org.mockito.ArgumentCaptor.forClass(SimpleMailMessage.class);
        verify(mail).send(sent.capture());
        assertThat(sent.getValue().getTo()).containsExactly("khach@example.com");
        assertThat(sent.getValue().getText()).contains("Ha Noi → Hai Phong", "08:00 ngày 02/01/2026", "BK-1", "250000.00");
        verify(notices).sent(7L);
    }

    @Test
    void failedDeliveryStaysQueuedForRetry() {
        when(notices.claim(any())).thenReturn(Optional.of(notice), Optional.empty());
        doThrow(new MailSendException("smtp down")).when(mail).send(any(SimpleMailMessage.class));
        worker.dispatch();
        verify(notices, never()).sent(anyLong());
    }
}
