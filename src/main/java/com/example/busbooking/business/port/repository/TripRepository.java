package com.example.busbooking.business.port.repository;

import com.example.busbooking.domain.model.Trip;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

public interface TripRepository {
    List<Trip> findForAdmin(Long routeId, com.example.busbooking.domain.enums.TripStatus status, LocalDate departureDate);

    Trip save(Trip trip);

    List<Trip> search(
            Long originId,
            Long destinationId,
            LocalDate departureDate, LocalDateTime now, int page, int size
    );

    Optional<Trip> findById(Long tripId);

    Optional<Trip> findByIdForUpdate(Long tripId);

    Optional<Trip> findReservationForUpdate(Long tripId);

    boolean hasOverlappingTrip(Long excludedId, Long vehicleId, LocalDateTime departure, LocalDateTime arrival);
    void advanceLifecycle(LocalDateTime now);

    boolean updateAvailableSeats(Long tripId, int seatDelta);
}
