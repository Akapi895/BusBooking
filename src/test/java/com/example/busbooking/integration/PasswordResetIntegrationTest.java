package com.example.busbooking.integration;

import com.example.busbooking.business.command.*;
import com.example.busbooking.business.port.notification.EmailVerificationSender;
import com.example.busbooking.business.port.notification.PasswordResetSender;
import com.example.busbooking.business.service.AuthService;
import com.example.busbooking.business.service.EmailVerificationService;
import com.example.busbooking.business.service.PasswordResetService;
import com.example.busbooking.domain.exception.InvalidCredentialsException;
import com.example.busbooking.domain.exception.InvalidVerificationCodeException;
import com.example.busbooking.domain.exception.VerificationRateLimitException;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@SpringBootTest(properties = {"auth.rate-limit.resend-limit=500", "auth.rate-limit.verify-limit=500"})
@ActiveProfiles("test")
@AutoConfigureMockMvc
class PasswordResetIntegrationTest {
    private static final String EMAIL = "reset.phase2.hoang@example.com";
    @Autowired AuthService auth;
    @Autowired EmailVerificationService verification;
    @Autowired PasswordResetService reset;
    @Autowired JdbcTemplate jdbc;
    @Autowired MockMvc mvc;
    @MockitoBean EmailVerificationSender verificationSender;
    @MockitoBean PasswordResetSender resetSender;
    private final Map<String, String> verifyCodes = new ConcurrentHashMap<>();
    private final Map<String, String> resetCodes = new ConcurrentHashMap<>();

    @BeforeEach
    void setup() {
        cleanup();
        doAnswer(call -> { verifyCodes.put(call.getArgument(0), call.getArgument(1)); return null; })
                .when(verificationSender).send(anyString(), anyString(), any());
        doAnswer(call -> { resetCodes.put(call.getArgument(0), call.getArgument(1)); return null; })
                .when(resetSender).send(anyString(), anyString(), any());
    }

    @AfterEach
    void cleanup() { jdbc.update("DELETE FROM users WHERE email LIKE 'reset.phase2.%@example.com'"); }

    @Test
    void codeResetsPasswordOnceAndRevokesEarlierTokens() throws Exception {
        String oldToken = verifiedLogin();
        reset.request(EMAIL);
        String code = resetCodes.get(EMAIL);
        String wrong = code.equals("000000") ? "111111" : "000000";

        assertThatThrownBy(() -> reset.reset(EMAIL, wrong, "NewPassword456")).isInstanceOf(InvalidVerificationCodeException.class);
        reset.reset(EMAIL, code, "NewPassword456");

        assertThatThrownBy(() -> reset.reset(EMAIL, code, "Another789xyz")).isInstanceOf(InvalidVerificationCodeException.class);
        assertThatThrownBy(() -> auth.login(new LoginCommand(EMAIL, "BusTrip2026"))).isInstanceOf(InvalidCredentialsException.class);
        mvc.perform(get("/api/auth/me").header("Authorization", "Bearer " + oldToken)).andExpect(status().isUnauthorized());
        String fresh = auth.login(new LoginCommand(EMAIL, "NewPassword456")).token().value();
        mvc.perform(get("/api/auth/me").header("Authorization", "Bearer " + fresh)).andExpect(status().isOk());
    }

    @Test
    void codeLocksAfterFiveWrongAttemptsAndResendHasACooldown() {
        verifiedLogin();
        reset.request(EMAIL);
        String code = resetCodes.get(EMAIL);
        String wrong = code.equals("000000") ? "111111" : "000000";
        for (int i = 0; i < 5; i++) {
            assertThatThrownBy(() -> reset.reset(EMAIL, wrong, "NewPassword456")).isInstanceOf(InvalidVerificationCodeException.class);
        }
        assertThatThrownBy(() -> reset.reset(EMAIL, code, "NewPassword456")).isInstanceOf(InvalidVerificationCodeException.class);
        assertThatThrownBy(() -> reset.request(EMAIL)).isInstanceOf(VerificationRateLimitException.class);
    }

    @Test
    void ineligibleAccountsGetTheSameAcceptedResponseAndNoEmail() throws Exception {
        auth.register(new RegisterCommand("Hoang", "reset.phase2.pending@example.com", "BusTrip2026", "0901234567"));
        for (String email : new String[] {"reset.phase2.pending@example.com", "reset.phase2.nobody@example.com"}) {
            mvc.perform(post("/api/auth/forgot-password").contentType(MediaType.APPLICATION_JSON)
                    .content("{\"email\":\"" + email + "\"}")).andExpect(status().isAccepted());
        }
        verifyNoInteractions(resetSender);
        mvc.perform(post("/api/auth/reset-password").contentType(MediaType.APPLICATION_JSON)
                .content("{\"email\":\"reset.phase2.nobody@example.com\",\"code\":\"123456\",\"newPassword\":\"NewPassword456\"}"))
                .andExpect(status().isBadRequest()).andExpect(jsonPath("$.error").value("INVALID_VERIFICATION_CODE"));
    }

    private String verifiedLogin() {
        auth.register(new RegisterCommand("Hoang", EMAIL, "BusTrip2026", "0901234567"));
        verification.verify(new VerifyEmailCommand(EMAIL, verifyCodes.get(EMAIL)));
        return auth.login(new LoginCommand(EMAIL, "BusTrip2026")).token().value();
    }
}
