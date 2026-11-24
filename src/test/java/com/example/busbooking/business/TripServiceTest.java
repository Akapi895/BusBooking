
package com.example.busbooking.business;

import com.example.busbooking.business.port.repository.TripRepository;
import com.example.busbooking.business.service.TripService;
import com.example.busbooking.domain.exception.ResourceNotFoundException;
import com.example.busbooking.domain.model.Trip;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.LocalDate;
import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class TripServiceTest {

    @Mock
    private TripRepository tripRepository;

    @org.mockito.Spy java.time.Clock clock = java.time.Clock.fixed(java.time.Instant.parse("2026-01-01T00:00:00Z"), java.time.ZoneOffset.UTC);
    private final java.time.LocalDateTime now = java.time.LocalDateTime.of(2026, 1, 1, 7, 0);

    @InjectMocks
    private TripService tripService;

    @Test
    void searchTrips_whenTripsExist_shouldReturnMatchingTrips() {
        Long originId = 1L;
        Long destinationId = 2L;
        LocalDate departureDate = LocalDate.of(2026, 10, 25);
        Trip trip = mock(Trip.class);
        List<Trip> expectedTrips = List.of(trip);

        when(tripRepository.search(originId, destinationId, departureDate, now, 0, 20))
                .thenReturn(expectedTrips);

        List<Trip> actualTrips = tripService.searchTrips(
                originId, destinationId, departureDate, 0, 20
        );

        assertEquals(expectedTrips, actualTrips);
        verify(tripRepository).search(originId, destinationId, departureDate, now, 0, 20);
    }

    @Test
    void searchTrips_whenNoTripsExist_shouldReturnEmptyList() {
        Long originId = 1L;
        Long destinationId = 2L;
        LocalDate departureDate = LocalDate.of(2026, 10, 25);

        when(tripRepository.search(originId, destinationId, departureDate, now, 0, 20))
                .thenReturn(List.of());

        List<Trip> result = tripService.searchTrips(
                originId, destinationId, departureDate, 0, 20
        );

        assertTrue(result.isEmpty());
        verify(tripRepository).search(originId, destinationId, departureDate, now, 0, 20);
    }

    @Test
    void searchTrips_whenAllFiltersAreNull_shouldDelegateNullsWithoutChangingThem() {
        when(tripRepository.search(null, null, null, now, 0, 20)).thenReturn(List.of());

        assertTrue(tripService.searchTrips(null, null, null, 0, 20).isEmpty());

        verify(tripRepository).search(null, null, null, now, 0, 20);
        verifyNoMoreInteractions(tripRepository);
    }

    @Test
    void getTripById_whenTripExists_shouldReturnTrip() {
        Long tripId = 10L;
        Trip expectedTrip = mock(Trip.class);

        when(tripRepository.findById(tripId))
                .thenReturn(Optional.of(expectedTrip));

        Trip actualTrip = tripService.getTripById(tripId);

        assertSame(expectedTrip, actualTrip);
        verify(tripRepository).findById(tripId);
    }

    @Test
    void getTripById_whenTripDoesNotExist_shouldThrowResourceNotFoundException() {
        Long tripId = 99L;

        when(tripRepository.findById(tripId))
                .thenReturn(Optional.empty());

        ResourceNotFoundException exception = assertThrows(
                ResourceNotFoundException.class,
                () -> tripService.getTripById(tripId)
        );

        assertEquals("Trip not found with id: 99", exception.getMessage());
        verify(tripRepository).findById(tripId);
    }
}
