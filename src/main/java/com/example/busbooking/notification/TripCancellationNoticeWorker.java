package com.example.busbooking.notification;

import com.example.busbooking.data.adapter.TripCancellationNotices;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.mail.MailException;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Clock;

@Component
@ConditionalOnProperty(name = "auth.email-outbox.enabled", havingValue = "true", matchIfMissing = true)
public class TripCancellationNoticeWorker {
    private static final Logger LOG = LoggerFactory.getLogger(TripCancellationNoticeWorker.class);
    private final TripCancellationNotices notices;
    private final JavaMailSender mail;
    private final String from;
    private final Clock clock;

    public TripCancellationNoticeWorker(TripCancellationNotices notices, JavaMailSender mail,
                                        @Value("${auth.mail-from}") String from, Clock clock) {
        this.notices = notices;
        this.mail = mail;
        this.from = from;
        this.clock = clock;
    }

    @Scheduled(fixedDelayString = "${auth.email-outbox.poll-ms:1000}")
    public void dispatch() {
        for (int i = 0; i < 10; i++) {
            var next = notices.claim(clock.instant());
            if (next.isEmpty()) return;
            var notice = next.get();
            try {
                mail.send(message(notice));
            } catch (MailException failure) {
                // Left claimed: the notice becomes due again when its lease ends.
                LOG.warn("{} failed", notice);
                continue;
            }
            notices.sent(notice.bookingId());
        }
    }

    SimpleMailMessage message(TripCancellationNotices.Notice notice) {
        var message = new SimpleMailMessage();
        message.setFrom(from);
        message.setTo(notice.email());
        message.setSubject("Chuyến xe đã bị hủy — Bus Booking");
        message.setText("Xin chào " + notice.passengerName() + ","
                + "\n\nChuyến " + notice.origin() + " → " + notice.destination()
                + " khởi hành lúc " + notice.departure() + " (giờ Việt Nam) đã bị hủy."
                + "\nVé " + notice.bookingCode() + " của bạn sẽ được hoàn " + notice.refund().toPlainString() + " VND."
                + "\nChúng tôi sẽ liên hệ khi hoàn tiền xong. Xin lỗi vì sự bất tiện này.");
        return message;
    }
}
