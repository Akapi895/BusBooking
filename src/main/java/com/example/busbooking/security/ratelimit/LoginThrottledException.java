package com.example.busbooking.security.ratelimit;

public class LoginThrottledException extends RuntimeException {
    private final long retryAfterSeconds;

    public LoginThrottledException(long retryAfterSeconds) {
        super("Too many login attempts for this account");
        this.retryAfterSeconds = retryAfterSeconds;
    }

    public long getRetryAfterSeconds() { return retryAfterSeconds; }
}
