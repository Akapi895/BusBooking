package com.example.busbooking.data.adapter;

import com.example.busbooking.business.port.repository.BookingRepository;
import com.example.busbooking.data.entity.BookingEntity;
import com.example.busbooking.data.mapper.BookingPersistenceMapper;
import com.example.busbooking.data.repository.SpringDataBookingRepository;
import com.example.busbooking.domain.enums.BookingStatus;
import com.example.busbooking.domain.model.Booking;
import org.springframework.stereotype.Component;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.PageRequest;
import java.util.List;
import java.util.Optional;

@Component
public class BookingRepositoryAdapter implements BookingRepository {
    private final SpringDataBookingRepository repository;
    private final BookingPersistenceMapper mapper;

    public BookingRepositoryAdapter(SpringDataBookingRepository repository, BookingPersistenceMapper mapper) {
        this.repository = repository;
        this.mapper = mapper;
    }

    public Booking save(Booking booking) {
        return mapper.toDomain(repository.save(mapper.toEntity(booking)));
    }
    public long countTakenSeats(Long tripId) {
        return repository.countSeats(tripId, List.of(BookingStatus.CONFIRMED, BookingStatus.HELD));
    }
    public Booking confirm(Long id) {
        repository.confirm(id);
        return repository.findById(id).map(mapper::toDomain).orElseThrow();
    }
    public int cancelTripHolds(Long tripId) {
        return repository.cancelTripHolds(tripId);
    }
    public long expireHolds(java.time.LocalDateTime now) {
        return repository.expireHolds(now);
    }
    public List<Booking> findForAdmin(Long userId, Long tripId, BookingStatus status) {
        return findForAdmin(userId, tripId, status, Pageable.unpaged());
    }
    public List<Booking> findForAdmin(Long userId, Long tripId, BookingStatus status, int page, int size) {
        return findForAdmin(userId, tripId, status, PageRequest.of(page, size));
    }
    private List<Booking> findForAdmin(Long userId, Long tripId, BookingStatus status, Pageable page) {
        return repository.findForAdmin(userId, tripId, status, userId == null, tripId == null, status == null, page)
                .stream().map(mapper::toDomain).toList();
    }
    public Optional<Booking> findById(Long id) {
        return repository.findById(id).map(mapper::toDomain);
    }
    public Optional<Booking> findByIdForUpdate(Long id) {
        return repository.findByIdForUpdate(id).map(mapper::toDomain);
    }
    public List<Booking> findByUserId(Long userId) {
        return repository.findAllByUserIdOrderByBookedAtDescIdDesc(userId, Pageable.unpaged())
                .stream().map(mapper::toDomain).toList();
    }
    public List<Booking> findByUserId(Long userId, int page, int size) {
        return repository.findAllByUserIdOrderByBookedAtDescIdDesc(userId, PageRequest.of(page, size))
                .stream().map(mapper::toDomain).toList();
    }
    public Booking updateStatus(Long id, BookingStatus status) {
        repository.updateStatus(id, status);
        return repository.findById(id).map(mapper::toDomain).orElseThrow();
    }
    public int markTripRefundPending(Long tripId, java.time.Instant noticeDue) {
        return repository.markTripRefundPending(tripId, noticeDue);
    }
    public Booking markRefunded(Long id, java.time.Instant refundedAt) {
        repository.markRefunded(id, refundedAt);
        return repository.findById(id).map(mapper::toDomain).orElseThrow();
    }
}
