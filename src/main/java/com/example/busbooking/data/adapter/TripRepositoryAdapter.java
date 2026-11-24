package com.example.busbooking.data.adapter;

import com.example.busbooking.business.port.repository.TripRepository;
import com.example.busbooking.data.entity.TripEntity;
import com.example.busbooking.data.mapper.TripPersistenceMapper;
import com.example.busbooking.data.repository.SpringDataTripRepository;
import com.example.busbooking.domain.model.Trip;
import com.example.busbooking.domain.exception.TripConflictException;
import org.hibernate.exception.ConstraintViolationException;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Component;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

@Component
public class TripRepositoryAdapter implements TripRepository {

    @jakarta.persistence.PersistenceContext
    private jakarta.persistence.EntityManager entityManager;

    private final SpringDataTripRepository springDataTripRepository;
    private final TripPersistenceMapper tripPersistenceMapper;

    public TripRepositoryAdapter(
            SpringDataTripRepository springDataTripRepository,
            TripPersistenceMapper tripPersistenceMapper) {
        this.springDataTripRepository = springDataTripRepository;
        this.tripPersistenceMapper = tripPersistenceMapper;
    }

    @Override
    public List<Trip> findForAdmin(Long routeId, com.example.busbooking.domain.enums.TripStatus status,
                                   LocalDate departureDate) {
        return springDataTripRepository.findForAdmin(routeId, status,
                departureDate == null ? null : departureDate.atStartOfDay(),
                departureDate == null ? null : departureDate.plusDays(1).atStartOfDay(),
                routeId == null, status == null, departureDate == null).stream()
                .map(tripPersistenceMapper::toDomain).toList();
    }

    @Override
    public Trip save(Trip trip) {
        TripEntity entity = trip.getId() == null ? new TripEntity()
                : springDataTripRepository.findById(trip.getId()).orElseThrow();
        entity.updateDetails(trip.getRouteId(), trip.getVehicleId(), trip.getDepartureTime(),
                trip.getArrivalTime(), trip.getPrice(), trip.getAvailableSeats(), trip.getStatus());
        try {
            entity = springDataTripRepository.saveAndFlush(entity);
        } catch (DataIntegrityViolationException failure) {
            if (failure.getCause() instanceof ConstraintViolationException constraint
                    && "trips_vehicle_schedule_no_overlap".equals(constraint.getConstraintName())) {
                throw new TripConflictException("Vehicle is assigned to an overlapping trip");
            }
            throw failure;
        }
        // Scalar foreign keys own these columns. Refresh only this trip after flushing so read-only
        // route/vehicle associations reflect changed IDs, without clearing other pending work.
        entityManager.refresh(entity);
        return tripPersistenceMapper.toDomain(entity);
    }

    @Override
    public List<Trip> search(
            Long originId,
            Long destinationId,
            LocalDate departureDate, LocalDateTime now, int page, int size) {

        return springDataTripRepository.searchFiltered(originId, destinationId,
                        departureDate == null ? now : departureDate.atStartOfDay(),
                        departureDate == null ? now : departureDate.plusDays(1).atStartOfDay(),
                        originId == null, destinationId == null, departureDate == null,
                        now, PageRequest.of(page, size)).stream()
                .map(tripPersistenceMapper::toDomain)
                .toList();
    }

    @Override
    public Optional<Trip> findById(Long tripId) {
        return springDataTripRepository.findDetailedById(tripId)
                .map(tripPersistenceMapper::toDomain);
    }

    @Override
    public Optional<Trip> findByIdForUpdate(Long tripId) {
        return springDataTripRepository.findByIdForUpdate(tripId)
                .map(tripPersistenceMapper::toDomain);
    }

    @Override
    public Optional<Trip> findReservationForUpdate(Long tripId) {
        return springDataTripRepository.findByIdForUpdate(tripId).map(t -> new Trip(
                t.getId(), t.getRouteId(), t.getVehicleId(), t.getDepartureTime(), t.getArrivalTime(),
                t.getPrice(), t.getAvailableSeats(), t.getStatus()));
    }

    @Override
    public boolean hasOverlappingTrip(Long excludedId, Long vehicleId, LocalDateTime departure, LocalDateTime arrival) {
        return springDataTripRepository.hasOverlappingTrip(excludedId, excludedId != null, vehicleId, departure, arrival);
    }

    @Override
    public void advanceLifecycle(LocalDateTime now) {
        springDataTripRepository.advanceLifecycle(now);
    }

    @Override
    public boolean updateAvailableSeats(Long tripId, int seatDelta) {
        return springDataTripRepository.updateAvailableSeats(tripId, seatDelta) == 1;
    }
}
