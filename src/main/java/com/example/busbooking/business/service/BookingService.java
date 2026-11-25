package com.example.busbooking.business.service;

import com.example.busbooking.business.port.repository.BookingRepository;
import com.example.busbooking.business.port.repository.BookingIdempotencyRepository;
import com.example.busbooking.business.port.repository.TripRepository;
import com.example.busbooking.domain.enums.BookingStatus;
import com.example.busbooking.domain.enums.TripStatus;
import com.example.busbooking.domain.exception.*;
import com.example.busbooking.domain.model.Booking;
import com.example.busbooking.domain.model.Trip;
import org.springframework.stereotype.Service;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.transaction.annotation.Transactional;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Clock;
import java.time.LocalDateTime;
import java.util.HexFormat;
import java.util.List;
import java.util.UUID;

@Service
public class BookingService {
    private final BookingRepository bookingRepository;
    private final TripRepository tripRepository;
    private final BookingIdempotencyRepository idempotency;
    private final Clock clock;

    public BookingService(BookingRepository bookingRepository, TripRepository tripRepository,
                          BookingIdempotencyRepository idempotency, Clock clock) {
        this.bookingRepository = bookingRepository;
        this.tripRepository = tripRepository;
        this.idempotency = idempotency;
        this.clock = clock;
    }

    @Transactional
    public Booking create(Long userId, Long tripId, String passengerName,
                          String passengerPhone, int quantity) {
        return create(userId, tripId, passengerName, passengerPhone, quantity, null);
    }

    @Transactional
    public Booking create(Long userId, Long tripId, String passengerName,
                          String passengerPhone, int quantity, String key) {
        if (quantity <= 0) throw new BusinessException("Quantity must be greater than zero");
        String name = AuthInputPolicy.fullName(passengerName);
        String phone = AuthInputPolicy.phone(passengerPhone);
        if (key != null) {
            if (!key.matches("[!-~]{1,128}")) {
                throw new InvalidAuthInputException("Idempotency-Key", "Use 1 to 128 visible ASCII characters");
            }
            String hash = hash(tripId, name, phone, quantity);
            var replay = idempotency.reserve(userId, key, hash, clock.instant());
            if (replay != null) {
                if (!hash.equals(replay.requestHash())) throw new IdempotencyConflictException();
                Booking stored = bookingRepository.findById(replay.bookingId()).orElseThrow();
                return new Booking(stored.getId(), stored.getBookingCode(), stored.getUserId(), stored.getTripId(),
                        stored.getPassengerName(), stored.getPassengerPhone(), stored.getQuantity(), stored.getUnitPrice(),
                        stored.getTotalAmount(), BookingStatus.CONFIRMED, stored.getBookedAt());
            }
        }
        var reservation = tripRepository.reserveSeats(tripId, quantity, TravelTime.now(clock))
                .orElseGet(() -> reserveAfterRechecking(tripId, quantity));
        LocalDateTime now = TravelTime.now(clock);
        // The UPDATE can wait for another transaction across the departure boundary.
        if (!reservation.departureTime().isAfter(now)) {
            throw new BusinessException("Trip is not available for booking");
        }
        BigDecimal total = reservation.price().multiply(BigDecimal.valueOf(quantity));
        Booking booking = new Booking(null, "BK-" + UUID.randomUUID().toString().replace("-", "").substring(0, 20), userId, tripId,
                name, phone, quantity, reservation.price(), total, BookingStatus.CONFIRMED, now);
        Booking saved = bookingRepository.save(booking);
        if (key != null) idempotency.complete(userId, key, saved.getId());
        return saved;
    }

    private TripRepository.SeatReservation reserveAfterRechecking(Long tripId, int quantity) {
        // Diagnose the miss against the locked row. A cancellation or admin change may already have made it bookable.
        Trip trip = tripRepository.findReservationForUpdate(tripId)
                .orElseThrow(() -> new ResourceNotFoundException("Trip not found with id: " + tripId));
        LocalDateTime now = TravelTime.now(clock);
        if (trip.getStatus() != TripStatus.SCHEDULED || !trip.getDepartureTime().isAfter(now)) {
            throw new BusinessException("Trip is not available for booking");
        }
        if (trip.getAvailableSeats() < quantity) {
            throw new InsufficientSeatsException("Not enough available seats");
        }
        return tripRepository.reserveSeats(tripId, quantity, now)
                .orElseThrow(() -> new InsufficientSeatsException("Not enough available seats"));
    }

    @Transactional(readOnly = true)
    public Booking get(Long userId, boolean admin, Long bookingId) {
        Booking booking = bookingRepository.findById(bookingId)
                .orElseThrow(() -> new ResourceNotFoundException("Booking not found with id: " + bookingId));
        verifyAccess(userId, admin, booking);
        return booking;
    }

    @Transactional(readOnly = true)
    public List<Booking> history(Long userId) {
        return bookingRepository.findByUserId(userId);
    }

    @Transactional(readOnly = true)
    public List<Booking> history(Long userId, int page, int size) {
        return bookingRepository.findByUserId(userId, page, size);
    }

    @Transactional(readOnly = true)
    public List<Booking> listForAdmin(Long userId, Long tripId, BookingStatus status) {
        return bookingRepository.findForAdmin(userId, tripId, status);
    }

    @Transactional(readOnly = true)
    public List<Booking> listForAdmin(Long userId, Long tripId, BookingStatus status, int page, int size) {
        return bookingRepository.findForAdmin(userId, tripId, status, page, size);
    }

    @Transactional
    public Booking cancel(Long userId, boolean admin, Long bookingId) {
        Booking booking = bookingRepository.findByIdForUpdate(bookingId)
                .orElseThrow(() -> new ResourceNotFoundException("Booking not found with id: " + bookingId));
        verifyAccess(userId, admin, booking);
        if (booking.getStatus() == BookingStatus.CANCELLED) {
            return booking;
        }
        Trip trip = tripRepository.findByIdForUpdate(booking.getTripId())
                .orElseThrow(() -> new ResourceNotFoundException(
                        "Trip not found with id: " + booking.getTripId()));
        if (!admin && !TravelTime.now(clock).isBefore(trip.getDepartureTime().minusMinutes(30))) {
            throw new BusinessException("The cancellation window has closed");
        }
        // Admins skip the 30-minute window, but a departed trip's seats can no longer be restored.
        if (trip.getStatus() != TripStatus.SCHEDULED || !TravelTime.now(clock).isBefore(trip.getDepartureTime())) {
            throw new BusinessException("Bookings can only be cancelled before the trip departs");
        }
        if (trip.getVehicle() == null
                || (long) trip.getAvailableSeats() + booking.getQuantity() > trip.getVehicle().seatCapacity()) {
            throw new BusinessException("Unable to restore available seats");
        }
        if (!tripRepository.updateAvailableSeats(booking.getTripId(), booking.getQuantity())) {
            throw new BusinessException("Unable to restore available seats");
        }
        return bookingRepository.updateStatus(bookingId, BookingStatus.CANCELLED);
    }

    private void verifyAccess(Long userId, boolean admin, Booking booking) {
        if (!admin && !booking.getUserId().equals(userId)) {
            throw new ForbiddenOperationException("You do not have access to this booking");
        }
    }

    private String hash(Long tripId, String name, String phone, int quantity) {
        String request = tripId + "\n" + name + "\n" + phone + "\n" + quantity;
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(request.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException(exception);
        }
    }

    @Scheduled(fixedDelay = 60_000)
    public void expireIdempotencyKeys() {
        idempotency.deleteExpired(clock.instant());
    }
}
