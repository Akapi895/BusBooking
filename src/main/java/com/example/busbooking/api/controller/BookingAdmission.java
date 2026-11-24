package com.example.busbooking.api.controller;

import com.example.busbooking.domain.exception.BookingBusyException;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Supplier;

@Component
public class BookingAdmission {
    private final ConcurrentHashMap<Long, Integer> active = new ConcurrentHashMap<>();
    private final int limit;

    public BookingAdmission(@Value("${booking.max-in-flight-per-trip:8}") int limit) {
        if (limit < 1) throw new IllegalArgumentException("booking.max-in-flight-per-trip must be positive");
        this.limit = limit;
    }

    public <T> T run(long tripId, Supplier<T> booking) {
        active.compute(tripId, (id, count) -> {
            if (count == null) return 1;
            if (count >= limit) throw new BookingBusyException();
            return count + 1;
        });
        try {
            return booking.get();
        } finally {
            active.computeIfPresent(tripId, (id, count) -> count == 1 ? null : count - 1);
        }
    }
}
