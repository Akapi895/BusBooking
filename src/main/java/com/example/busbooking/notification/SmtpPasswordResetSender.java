package com.example.busbooking.notification;

import com.example.busbooking.business.port.notification.PasswordResetSender;
import com.example.busbooking.domain.exception.EmailDeliveryException;
import com.example.busbooking.business.service.TravelTime;
import org.springframework.mail.MailException;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import java.time.Instant;

public final class SmtpPasswordResetSender implements PasswordResetSender {
    private final JavaMailSender sender;
    private final String from;

    public SmtpPasswordResetSender(JavaMailSender sender, String from) {
        this.sender = sender;
        this.from = from;
    }

    @Override
    public void send(String email, String code, Instant expiresAt) {
        SimpleMailMessage message = new SimpleMailMessage();
        message.setFrom(from);
        message.setTo(email);
        message.setSubject("Đặt lại mật khẩu — Bus Booking");
        message.setText("Mã đặt lại mật khẩu của bạn: " + code
                + "\nMã có hiệu lực trong 10 phút, đến " + TravelTime.display(expiresAt)
                + " (giờ Việt Nam).\nKhông chia sẻ mã này với người khác."
                + "\nNếu bạn không yêu cầu đặt lại mật khẩu, hãy bỏ qua email này.");
        try { sender.send(message); }
        catch (MailException failure) {
            // Do not propagate SMTP details that may contain addresses, credentials or message body.
            throw new EmailDeliveryException();
        }
    }
}
