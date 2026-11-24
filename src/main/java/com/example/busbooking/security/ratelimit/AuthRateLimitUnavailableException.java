package com.example.busbooking.security.ratelimit;

public final class AuthRateLimitUnavailableException extends RuntimeException {
    public AuthRateLimitUnavailableException(Throwable cause) {
        super("Auth rate limit store unavailable", cause);
    }
}
