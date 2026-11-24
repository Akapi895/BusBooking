package com.example.busbooking.data;

import com.example.busbooking.data.adapter.TripRepositoryAdapter;
import com.example.busbooking.data.entity.TripEntity;
import com.example.busbooking.data.mapper.TripPersistenceMapper;
import com.example.busbooking.data.repository.SpringDataTripRepository;
import com.example.busbooking.domain.model.Trip;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.LocalDate;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class TripRepositoryAdapterTest {

    @Mock
    private SpringDataTripRepository repository;

    @Mock
    private TripPersistenceMapper mapper;

    @Mock
    private Trip trip;

    private final java.time.LocalDateTime now = LocalDate.of(2026, 10, 24).atStartOfDay();

    @Test
    void search_withoutDateSkipsBothDateBounds() {
        when(repository.searchFiltered(null, 2L, now, now, true, false, true, now, org.springframework.data.domain.PageRequest.of(0, 20))).thenReturn(List.of());
        TripRepositoryAdapter adapter = new TripRepositoryAdapter(repository, mapper, mock(org.springframework.jdbc.core.JdbcTemplate.class));

        assertEquals(List.of(), adapter.search(null, 2L, null, now, 0, 20));

        verify(repository).searchFiltered(null, 2L, now, now, true, false, true, now, org.springframework.data.domain.PageRequest.of(0, 20));
        verifyNoInteractions(mapper);
    }

    @Test
    void search_withDateUsesHalfOpenWholeDayRange() {
        TripEntity entity = mock(TripEntity.class);
        when(repository.searchFiltered(1L, 2L, LocalDate.of(2026, 10, 25).atStartOfDay(),
                LocalDate.of(2026, 10, 26).atStartOfDay(), false, false, false, now,
                org.springframework.data.domain.PageRequest.of(0, 20)))
                .thenReturn(List.of(entity));
        when(mapper.toDomain(entity)).thenReturn(trip);
        TripRepositoryAdapter adapter = new TripRepositoryAdapter(repository, mapper, mock(org.springframework.jdbc.core.JdbcTemplate.class));

        assertEquals(List.of(trip), adapter.search(1L, 2L, LocalDate.of(2026, 10, 25), now, 0, 20));

        verify(mapper).toDomain(entity);
    }
}
