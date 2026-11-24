package com.example.busbooking.security.ratelimit;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;

import java.util.ArrayList;
import java.util.UUID;
import java.util.concurrent.Callable;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;

@EnabledIfEnvironmentVariable(named = "TEST_REDIS_PORT", matches = "[0-9]+")
class RedisRateLimitIntegrationTest {
    private static final String LOGIN = "/api/auth/login";
    private static final String CLIENT = "192.0.2.10";

    @Test
    void independentClientsShareOneAtomicQuotaPerAddressAndEndpoint() throws Exception {
        int port = Integer.parseInt(System.getenv("TEST_REDIS_PORT"));
        var first = new LettuceConnectionFactory("127.0.0.1", port);
        var second = new LettuceConnectionFactory("127.0.0.1", port);
        first.afterPropertiesSet();
        second.afterPropertiesSet();
        var properties = new AuthRateLimitProperties();
        properties.setRedisPrefix("busbooking:test:" + UUID.randomUUID());
        properties.setLoginLimit(4);

        var redis = new StringRedisTemplate(first);
        var firstLimiter = new RedisAuthRateLimiter(redis, properties);
        var secondLimiter = new RedisAuthRateLimiter(new StringRedisTemplate(second), properties);
        try (var pool = Executors.newFixedThreadPool(8)) {
            var requests = new ArrayList<Callable<AuthRateLimiter.Decision>>();
            for (int i = 0; i < 16; i++) {
                var limiter = i % 2 == 0 ? firstLimiter : secondLimiter;
                requests.add(() -> limiter.consume(CLIENT, LOGIN));
            }
            var decisions = new ArrayList<AuthRateLimiter.Decision>();
            for (var result : pool.invokeAll(requests, 15, TimeUnit.SECONDS)) decisions.add(result.get());
            assertThat(decisions.stream().filter(AuthRateLimiter.Decision::allowed)).hasSize(4);
            assertThat(decisions).filteredOn(decision -> !decision.allowed())
                    .allSatisfy(decision -> assertThat(decision.retryAfterSeconds()).isBetween(1L, 60L));
            assertThat(secondLimiter.consume("192.0.2.11", LOGIN).allowed()).isTrue();
            assertThat(secondLimiter.consume(CLIENT, "/api/auth/register").allowed()).isTrue();
            assertThat(redis.getExpire(properties.getRedisPrefix() + ":" + LOGIN + ":" + CLIENT)).isBetween(1L, 60L);
        } finally {
            second.destroy();
            first.destroy();
        }
    }
}
