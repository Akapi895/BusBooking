package com.example.busbooking.security.ratelimit;

public interface AuthRateLimiter {
    Decision consume(String remoteAddress, String path);

    record Decision(boolean allowed, long retryAfterSeconds) { }
}
