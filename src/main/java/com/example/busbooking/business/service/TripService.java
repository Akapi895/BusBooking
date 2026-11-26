package com.example.busbooking.business.service;

import com.example.busbooking.business.port.repository.TripRepository;
import com.example.busbooking.business.port.repository.RouteRepository;
import com.example.busbooking.business.port.repository.VehicleRepository;
import com.example.busbooking.business.port.repository.BookingRepository;
import com.example.busbooking.business.command.SaveTripCommand;
import com.example.busbooking.domain.enums.*;
import com.example.busbooking.domain.model.Vehicle;
import com.example.busbooking.domain.exception.BusinessException;
import com.example.busbooking.domain.exception.TripConflictException;
import com.example.busbooking.domain.exception.ResourceNotFoundException;
import com.example.busbooking.domain.model.Trip;
import org.springframework.stereotype.Service;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDate;
import java.time.Clock;
import java.util.List;

@Service
public class TripService {

    private final TripRepository tripRepository;
    private final RouteRepository routeRepository;
    private final VehicleRepository vehicleRepository;
    private final BookingRepository bookingRepository;
    private final Clock clock;

    public TripService(TripRepository tripRepository, RouteRepository routeRepository,
                       VehicleRepository vehicleRepository, BookingRepository bookingRepository, Clock clock) {
        this.tripRepository = tripRepository;
        this.routeRepository = routeRepository;
        this.vehicleRepository = vehicleRepository;
        this.bookingRepository = bookingRepository;
        this.clock = clock;
    }

    @Transactional(readOnly = true)
    public List<Trip> listForAdmin(Long routeId, TripStatus status, LocalDate departureDate) {
        return tripRepository.findForAdmin(routeId, status, departureDate);
    }

    @Transactional
    public Trip create(SaveTripCommand command) {
        Vehicle vehicle = validate(command);
        requireAvailableVehicle(null, command);
        return tripRepository.save(new Trip(null, command.routeId(), command.vehicleId(),
                command.departureTime(), command.arrivalTime(), command.price(),
                vehicle.seatCapacity(), TripStatus.SCHEDULED));
    }

    @Transactional
    public Trip update(Long tripId, SaveTripCommand command) {
        Trip current = lockedTrip(tripId);
        requireScheduled(current);
        Vehicle vehicle = validate(command);
        boolean itineraryChanged = !current.getRouteId().equals(command.routeId())
                || !current.getDepartureTime().equals(command.departureTime())
                || !current.getArrivalTime().equals(command.arrivalTime());
        boolean vehicleChanged = !current.getVehicleId().equals(command.vehicleId());
        long takenSeats = itineraryChanged || vehicleChanged ? bookingRepository.countTakenSeats(tripId) : 0;
        if (itineraryChanged && takenSeats > 0) {
            throw new TripConflictException("The route and times cannot change after seats have been booked");
        }
        if (itineraryChanged || vehicleChanged) requireAvailableVehicle(tripId, command);
        int availableSeats = current.getAvailableSeats();
        if (vehicleChanged) {
            // Booking creation/cancellation takes this same trip lock before changing seats/status.
            if (takenSeats > vehicle.seatCapacity()) {
                throw new TripConflictException("Vehicle capacity is smaller than confirmed booked seats");
            }
            availableSeats = vehicle.seatCapacity() - (int) takenSeats;
        }
        return tripRepository.save(new Trip(tripId, command.routeId(), command.vehicleId(),
                command.departureTime(), command.arrivalTime(), command.price(), availableSeats, current.getStatus()));
    }

    private Trip lockedTrip(Long tripId) {
        return tripRepository.findByIdForUpdate(tripId)
                .orElseThrow(() -> new ResourceNotFoundException("Trip not found with id: " + tripId));
    }

    @Transactional
    public Trip cancel(Long tripId) {
        Trip current = lockedTrip(tripId);
        if (current.getStatus() == TripStatus.CANCELLED) return current;
        requireScheduled(current);
        // Confirmed bookings become refunds owed; each customer is emailed through the notice outbox.
        // shortcut: locks trip then bookings, the reverse of booking cancellation; a rare deadlock
        // surfaces as a retryable 503. Lock the trip first in booking cancellation if it shows up.
        long takenSeats = bookingRepository.countTakenSeats(tripId);
        // Holds go first: a confirmation racing this cancellation then lands before the refund update and is refunded.
        bookingRepository.cancelTripHolds(tripId);
        if (takenSeats > 0) bookingRepository.markTripRefundPending(tripId, clock.instant());
        return tripRepository.save(new Trip(tripId, current.getRouteId(), current.getVehicleId(),
                current.getDepartureTime(), current.getArrivalTime(), current.getPrice(),
                current.getAvailableSeats() + (int) takenSeats, TripStatus.CANCELLED));
    }

    private void requireScheduled(Trip trip) {
        if (trip.getStatus() != TripStatus.SCHEDULED || !trip.getDepartureTime().isAfter(TravelTime.now(clock))) {
            throw new TripConflictException("Only scheduled trips can be changed or cancelled");
        }
    }

    private void requireAvailableVehicle(Long tripId, SaveTripCommand command) {
        if (tripRepository.hasOverlappingTrip(tripId, command.vehicleId(), command.departureTime(), command.arrivalTime())) {
            throw new TripConflictException("Vehicle is assigned to an overlapping trip");
        }
    }

    @Scheduled(fixedDelayString = "${booking.lifecycle.interval-ms:30000}")
    @Transactional
    public void advanceTripLifecycle() {
        var now = TravelTime.now(clock);
        tripRepository.advanceLifecycle(now);
    }

    private Vehicle validate(SaveTripCommand command) {
        if (command == null || command.routeId() == null || command.routeId() <= 0
                || command.vehicleId() == null || command.vehicleId() <= 0
                || command.departureTime() == null || command.arrivalTime() == null
                || !command.arrivalTime().isAfter(command.departureTime())
                || command.price() == null || command.price().signum() < 0
                || command.price().scale() > 2
                || command.price().compareTo(new java.math.BigDecimal("9999999999.99")) > 0) {
            throw new BusinessException("Invalid trip times, price or references");
        }
        // Serialize trip assignment with route endpoint/status changes.
        var route = routeRepository.findByIdForUpdate(command.routeId())
                .orElseThrow(() -> new ResourceNotFoundException("Route not found with id: " + command.routeId()));
        // Serialize trip assignment with vehicle capacity/status/identity changes.
        Vehicle vehicle = vehicleRepository.findByIdForUpdate(command.vehicleId())
                .orElseThrow(() -> new ResourceNotFoundException("Vehicle not found with id: " + command.vehicleId()));
        if (route.status() != RouteStatus.ACTIVE || vehicle.status() != VehicleStatus.ACTIVE) {
            throw new BusinessException("Route and vehicle must be active");
        }
        return vehicle;
    }

    public List<Trip> searchTrips(
            Long originId,
            Long destinationId,
            LocalDate departureDate, int page, int size) {

        return tripRepository.search(
                originId,
                destinationId,
                departureDate, TravelTime.now(clock), page, size
        );
    }

    public Trip getTripById(Long tripId) {
        return tripRepository.findById(tripId)
                .orElseThrow(() ->
                        new ResourceNotFoundException(
                                "Trip not found with id: " + tripId
                        )
                );
    }
}
