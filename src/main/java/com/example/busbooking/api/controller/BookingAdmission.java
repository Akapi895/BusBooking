package com.example.busbooking.api.controller;

import com.example.busbooking.domain.exception.BookingBusyException;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Semaphore;
import java.util.function.Supplier;

@Component
public class BookingAdmission {
    private final ConcurrentHashMap<Long, Integer> active = new ConcurrentHashMap<>();
    private final int limit;
    // Bookings wait on trip row locks while holding a pool connection; several hot trips together
    // must not take every connection of this instance, so the total is capped below the pool size.
    private final Semaphore total;

    public BookingAdmission(@Value("${booking.max-in-flight-per-trip:8}") int limit,
                            @Value("${booking.max-in-flight-total:8}") int totalLimit) {
        if (limit < 1) throw new IllegalArgumentException("booking.max-in-flight-per-trip must be positive");
        if (totalLimit < 1) throw new IllegalArgumentException("booking.max-in-flight-total must be positive");
        this.limit = limit;
        this.total = new Semaphore(totalLimit);
    }

    public <T> T run(long tripId, Supplier<T> booking) {
        if (!total.tryAcquire()) throw new BookingBusyException();
        try {
            active.compute(tripId, (id, count) -> {
                if (count == null) return 1;
                if (count >= limit) throw new BookingBusyException();
                return count + 1;
            });
        } catch (BookingBusyException busy) {
            total.release();
            throw busy;
        }
        try {
            return booking.get();
        } finally {
            active.computeIfPresent(tripId, (id, count) -> count == 1 ? null : count - 1);
            total.release();
        }
    }
}
