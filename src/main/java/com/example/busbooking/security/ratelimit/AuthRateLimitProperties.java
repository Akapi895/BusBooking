package com.example.busbooking.security.ratelimit;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "auth.rate-limit")
public class AuthRateLimitProperties {
    public enum Backend { LOCAL, REDIS }

    // Internal quota key: counts login attempts per account, not per client address.
    public static final String LOGIN_ACCOUNT = "/api/auth/login:account";

    private Backend backend = Backend.LOCAL;
    private String redisPrefix = "busbooking:auth-rate:v1";
    private long windowSeconds = 60;
    private int maxKeys = 10_000;
    private int registerLimit = 5;
    private int loginLimit = 10;
    private int loginAccountLimit = 5;
    private int verifyLimit = 20;
    private int resendLimit = 5;

    public Backend getBackend() { return backend; }
    public void setBackend(Backend value) { backend = value; }
    public String getRedisPrefix() { return redisPrefix; }
    public void setRedisPrefix(String value) { redisPrefix = value; }
    public long getWindowSeconds() { return windowSeconds; }
    public void setWindowSeconds(long value) { windowSeconds = value; }
    public int getMaxKeys() { return maxKeys; }
    public void setMaxKeys(int value) { maxKeys = value; }
    public int getRegisterLimit() { return registerLimit; }
    public void setRegisterLimit(int value) { registerLimit = value; }
    public int getLoginLimit() { return loginLimit; }
    public void setLoginLimit(int value) { loginLimit = value; }
    public int getLoginAccountLimit() { return loginAccountLimit; }
    public void setLoginAccountLimit(int value) { loginAccountLimit = value; }
    public int getVerifyLimit() { return verifyLimit; }
    public void setVerifyLimit(int value) { verifyLimit = value; }
    public int getResendLimit() { return resendLimit; }
    public void setResendLimit(int value) { resendLimit = value; }

    public int quota(String path) {
        return switch (path) {
            case "/api/auth/register" -> registerLimit;
            case "/api/auth/login" -> loginLimit;
            case LOGIN_ACCOUNT -> loginAccountLimit;
            case "/api/auth/forgot-password" -> resendLimit;
            case "/api/auth/reset-password" -> verifyLimit;
            case "/api/auth/verify-email" -> verifyLimit;
            case "/api/auth/resend-verification" -> resendLimit;
            default -> 0;
        };
    }

    public void validate() {
        if (backend == null || redisPrefix == null || !redisPrefix.matches("[a-zA-Z0-9:_-]{1,100}")
                || windowSeconds < 1 || windowSeconds > 86400 || maxKeys < 1 || maxKeys > 100_000
                || registerLimit < 1 || loginLimit < 1 || loginAccountLimit < 1 || loginAccountLimit > 1_000_000 || verifyLimit < 1 || resendLimit < 1
                || registerLimit > 1_000_000 || loginLimit > 1_000_000
                || verifyLimit > 1_000_000 || resendLimit > 1_000_000) {
            throw new IllegalStateException("Invalid auth rate limit configuration");
        }
    }
}
