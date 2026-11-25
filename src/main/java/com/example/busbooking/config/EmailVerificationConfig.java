package com.example.busbooking.config;

import com.example.busbooking.business.port.notification.EmailVerificationSender;
import com.example.busbooking.business.port.notification.VerificationQueue;
import com.example.busbooking.business.port.repository.EmailVerificationRepository;
import com.example.busbooking.business.port.security.VerificationCodeProvider;
import com.example.busbooking.business.service.EmailVerificationService;
import com.example.busbooking.notification.SmtpEmailVerificationSender;
import com.example.busbooking.notification.SmtpPasswordResetSender;
import com.example.busbooking.business.port.notification.PasswordResetSender;
import com.example.busbooking.business.port.repository.PasswordResetRepository;
import com.example.busbooking.business.port.security.PasswordHasher;
import com.example.busbooking.business.service.PasswordResetService;
import com.example.busbooking.security.HmacVerificationCodeProvider;
import com.example.busbooking.security.VerificationPayloadCipher;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.mail.javamail.JavaMailSender;
import java.time.Clock;

@Configuration
public class EmailVerificationConfig {
    @Bean
    public VerificationCodeProvider verificationCodeProvider(@Value("${auth.email-otp-secret}") String secret) {
        return new HmacVerificationCodeProvider(secret);
    }

    @Bean
    public EmailVerificationSender emailVerificationSender(JavaMailSender sender,
                                                           @Value("${auth.mail-from}") String from) {
        return new SmtpEmailVerificationSender(sender, from);
    }

    @Bean
    @ConditionalOnProperty(name = "auth.email-outbox.enabled", havingValue = "true", matchIfMissing = true)
    public VerificationPayloadCipher verificationPayloadCipher(@Value("${auth.email-outbox.secret}") String secret) {
        return new VerificationPayloadCipher(secret);
    }

    @Bean
    public EmailVerificationService emailVerificationService(EmailVerificationRepository repository,
            VerificationCodeProvider codes, EmailVerificationSender sender, Clock clock,
            ObjectProvider<VerificationQueue> queue) {
        return new EmailVerificationService(repository, codes, sender, clock, queue.getIfAvailable());
    }

    @Bean
    public PasswordResetSender passwordResetSender(JavaMailSender sender, @Value("${auth.mail-from}") String from) {
        return new SmtpPasswordResetSender(sender, from);
    }

    @Bean
    public PasswordResetService passwordResetService(PasswordResetRepository repository, VerificationCodeProvider codes,
            PasswordResetSender sender, PasswordHasher passwords, Clock clock) {
        return new PasswordResetService(repository, codes, sender, passwords, clock);
    }
}
