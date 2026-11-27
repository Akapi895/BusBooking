package com.example.busbooking.business.service;

import java.time.Clock;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;

public final class TravelTime {
    public static final ZoneId VIETNAM = ZoneId.of("Asia/Ho_Chi_Minh");
    private static final DateTimeFormatter DISPLAY = DateTimeFormatter.ofPattern("HH:mm 'ngày' dd/MM/yyyy");

    private TravelTime() {}

    public static LocalDateTime now(Clock clock) {
        return LocalDateTime.ofInstant(clock.instant(), VIETNAM);
    }

    /** Human-readable Vietnam time for messages, e.g. "07:10 ngày 22/10/2026". */
    public static String display(Instant instant) {
        return display(LocalDateTime.ofInstant(instant, VIETNAM));
    }

    /** Same format for a value that is already Vietnam local time (trip departures). */
    public static String display(LocalDateTime vietnamTime) {
        return DISPLAY.format(vietnamTime);
    }
}
