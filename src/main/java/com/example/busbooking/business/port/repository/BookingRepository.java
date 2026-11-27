package com.example.busbooking.business.port.repository;

import com.example.busbooking.domain.model.Booking;

import java.util.List;
import java.util.Optional;

public interface BookingRepository {
    /** Seats a trip has given out: confirmed bookings plus unexpired holds. */
    long countTakenSeats(Long tripId);
    List<Booking> findForAdmin(Long userId, Long tripId, com.example.busbooking.domain.enums.BookingStatus status);
    List<Booking> findForAdmin(Long userId, Long tripId, com.example.busbooking.domain.enums.BookingStatus status,
                               int page, int size);
    Booking save(Booking booking);
    Optional<Booking> findById(Long bookingId);
    Optional<Booking> findByIdForUpdate(Long bookingId);
    List<Booking> findByUserId(Long userId);
    List<Booking> findByUserId(Long userId, int page, int size);
    Booking updateStatus(Long bookingId, com.example.busbooking.domain.enums.BookingStatus status);
    /** Moves every confirmed booking of the trip to REFUND_PENDING and queues its cancellation email. */
    int markTripRefundPending(Long tripId, java.time.Instant noticeDue);
    Booking markRefunded(Long bookingId, java.time.Instant refundedAt);
    Booking confirm(Long bookingId);
    /** Cancels every HELD booking of the trip; the caller restores their seats. */
    int cancelTripHolds(Long tripId);
    /** Moves lapsed holds to EXPIRED and returns their seats to the trips, in one statement. */
    long expireHolds(java.time.LocalDateTime now);
}
