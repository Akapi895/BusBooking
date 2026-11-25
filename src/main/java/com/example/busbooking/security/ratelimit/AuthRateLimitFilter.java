package com.example.busbooking.security.ratelimit;

import com.example.busbooking.exception.ApiErrorWriter;
import jakarta.servlet.*;
import jakarta.servlet.http.*;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.security.web.servlet.util.matcher.PathPatternRequestMatcher;
import org.springframework.security.web.util.matcher.RequestMatcher;
import org.springframework.web.filter.OncePerRequestFilter;
import java.io.IOException;
import java.util.List;

public final class AuthRateLimitFilter extends OncePerRequestFilter {
    private static final List<Endpoint> ENDPOINTS = List.of("register", "login", "verify-email", "resend-verification",
            "forgot-password", "reset-password")
            .stream().map(name -> {
                String path = "/api/auth/" + name;
                return new Endpoint(path, PathPatternRequestMatcher.withDefaults().matcher(HttpMethod.POST, path));
            }).toList();
    private final AuthRateLimiter limiter;
    private final ApiErrorWriter errors;

    public AuthRateLimitFilter(AuthRateLimiter limiter, ApiErrorWriter errors) {
        this.limiter = limiter;
        this.errors = errors;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        for (Endpoint endpoint : ENDPOINTS) {
            if (!endpoint.matcher().matches(request)) { continue; }
            // Tomcat can resolve the client address when the deployment configures a trusted proxy.
            AuthRateLimiter.Decision decision;
            try {
                decision = limiter.consume(request.getRemoteAddr(), endpoint.path());
            } catch (AuthRateLimitUnavailableException failure) {
                response.setHeader(HttpHeaders.RETRY_AFTER, "1");
                errors.write(request, response, 503, "SERVICE_UNAVAILABLE", "Please retry shortly");
                return;
            }
            if (!decision.allowed()) {
                response.setHeader(HttpHeaders.RETRY_AFTER, Long.toString(decision.retryAfterSeconds()));
                errors.write(request, response, 429, "RATE_LIMITED", "Too many requests; please try again later");
                return;
            }
            break;
        }
        chain.doFilter(request, response);
    }

    private record Endpoint(String path, RequestMatcher matcher) { }
}
