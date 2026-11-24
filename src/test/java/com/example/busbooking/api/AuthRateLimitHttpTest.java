package com.example.busbooking.api;

import com.example.busbooking.business.service.AuthService;
import com.example.busbooking.domain.exception.InvalidCredentialsException;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.*;
import java.net.URI;
import java.util.concurrent.atomic.AtomicInteger;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@SpringBootTest(properties = {"auth.rate-limit.login-limit=2", "auth.rate-limit.login-account-limit=3", "springdoc.api-docs.enabled=false", "springdoc.swagger-ui.enabled=false"})
@ActiveProfiles("test")
@AutoConfigureMockMvc
class AuthRateLimitHttpTest {
    private static final AtomicInteger IPS = new AtomicInteger();
    @Autowired MockMvc mvc;
    @MockitoBean AuthService auth;
    private String ip;
    private String loginBody;

    @BeforeEach
    void setup() {
        int run = IPS.incrementAndGet();
        ip = "192.0.2." + run;
        loginBody = body("user" + run + "@example.com");
        when(auth.login(any())).thenThrow(new InvalidCredentialsException());
    }

    @Test
    void countsFailuresIgnoresForgedForwardedHeadersAndProvidesRetryAfter() throws Exception {
        attempt(loginBody, "1.1.1.1").andExpect(status().isUnauthorized());
        attempt(loginBody, "2.2.2.2").andExpect(status().isUnauthorized());
        var blocked = attempt(loginBody, "3.3.3.3").andExpect(status().isTooManyRequests())
                .andExpect(jsonPath("$.error").value("RATE_LIMITED"))
                .andExpect(header().exists("Retry-After")).andReturn();
        assertThat(Integer.parseInt(blocked.getResponse().getHeader("Retry-After"))).isBetween(1, 60);
        verify(auth, times(2)).login(any());
    }

    @Test
    void malformedBodyCountsAndTheFilterDoesNotConsumeTheBody() throws Exception {
        attempt("{broken", "1.1.1.1").andExpect(status().isBadRequest());
        attempt(loginBody, "1.1.1.1").andExpect(status().isUnauthorized());
        attempt(loginBody, "1.1.1.1").andExpect(status().isTooManyRequests());
        verify(auth, times(1)).login(any());
    }

    @Test
    void encodedEndpointCannotBypassProtection() throws Exception {
        attempt(loginBody, "1.1.1.1").andExpect(status().isUnauthorized());
        attempt(loginBody, "1.1.1.1").andExpect(status().isUnauthorized());
        var response = mvc.perform(post(URI.create("/api/auth/%6cogin")).with(request -> { request.setRemoteAddr(ip); return request; })
                .contentType(MediaType.APPLICATION_JSON).content(loginBody)).andReturn().getResponse();
        assertThat(response.getStatus()).isIn(400, 429);
        verify(auth, times(2)).login(any());
    }

    @Test
    void oneAccountIsThrottledAcrossClientAddresses() throws Exception {
        for (int i = 1; i <= 3; i++) {
            attemptFrom("198.51.100." + i, loginBody).andExpect(status().isUnauthorized());
        }
        attemptFrom("198.51.100.4", loginBody.replace("user", "USER")).andExpect(status().isTooManyRequests())
                .andExpect(jsonPath("$.error").value("RATE_LIMITED")).andExpect(header().exists("Retry-After"));
        attemptFrom("198.51.100.5", body("other" + ip + "@example.com")).andExpect(status().isUnauthorized());
        verify(auth, times(4)).login(any());
    }

    @Test
    void docsAreNotPublicWhenDisabled() throws Exception {
        mvc.perform(get("/v3/api-docs")).andExpect(status().isUnauthorized());
        mvc.perform(get("/swagger-ui/index.html")).andExpect(status().isUnauthorized());
    }

    private static String body(String email) {
        return "{\"email\":\"" + email + "\",\"password\":\"Password123\"}";
    }

    private ResultActions attemptFrom(String address, String body) throws Exception {
        return mvc.perform(post("/api/auth/login").with(request -> { request.setRemoteAddr(address); return request; })
                .contentType(MediaType.APPLICATION_JSON).content(body));
    }

    private ResultActions attempt(String body, String forwarded) throws Exception {
        return mvc.perform(post("/api/auth/login").with(request -> { request.setRemoteAddr(ip); return request; })
                .header("X-Forwarded-For", forwarded).contentType(MediaType.APPLICATION_JSON).content(body));
    }
}
