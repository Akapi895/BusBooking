package com.example.busbooking.security.ratelimit;

import org.springframework.dao.DataAccessException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.RedisScript;

import java.util.List;
import java.util.Objects;

public final class RedisAuthRateLimiter implements AuthRateLimiter {
    private static final RedisScript<Long> CONSUME = RedisScript.of("""
            local count = redis.call('GET', KEYS[1])
            if not count then
                redis.call('SET', KEYS[1], '1', 'PX', ARGV[2])
                return 0
            end
            if tonumber(count) >= tonumber(ARGV[1]) then
                return math.max(1, redis.call('PTTL', KEYS[1]))
            end
            redis.call('INCR', KEYS[1])
            return 0
            """, Long.class);

    private final StringRedisTemplate redis;
    private final AuthRateLimitProperties properties;

    public RedisAuthRateLimiter(StringRedisTemplate redis, AuthRateLimitProperties properties) {
        properties.validate();
        this.redis = redis;
        this.properties = properties;
    }

    @Override
    public Decision consume(String remoteAddress, String path) {
        int quota = properties.quota(path);
        if (quota == 0) return new Decision(true, 0);

        String key = properties.getRedisPrefix() + ":" + path + ":" + Objects.requireNonNullElse(remoteAddress, "unknown");
        Long retryMillis;
        try {
            retryMillis = redis.execute(CONSUME, List.of(key), Integer.toString(quota),
                    Long.toString(properties.getWindowSeconds() * 1000));
        } catch (DataAccessException failure) {
            throw new AuthRateLimitUnavailableException(failure);
        }
        if (retryMillis == null) throw new AuthRateLimitUnavailableException(null);
        return new Decision(retryMillis == 0, (retryMillis + 999) / 1000);
    }
}
