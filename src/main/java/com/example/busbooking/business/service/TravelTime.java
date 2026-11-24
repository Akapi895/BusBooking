package com.example.busbooking.business.service;

import java.time.Clock;
import java.time.LocalDateTime;
import java.time.ZoneId;

public final class TravelTime {
    private static final ZoneId VIETNAM = ZoneId.of("Asia/Ho_Chi_Minh");

    private TravelTime() {}

    public static LocalDateTime now(Clock clock) {
        return LocalDateTime.ofInstant(clock.instant(), VIETNAM);
    }
}
