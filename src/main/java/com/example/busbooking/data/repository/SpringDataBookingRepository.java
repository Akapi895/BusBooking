package com.example.busbooking.data.repository;

import com.example.busbooking.data.entity.BookingEntity;
import com.example.busbooking.domain.enums.BookingStatus;
import jakarta.persistence.LockModeType;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.*;
import org.springframework.data.repository.query.Param;
import java.util.List;
import java.util.Optional;

public interface SpringDataBookingRepository extends JpaRepository<BookingEntity, Long> {
    @Query("SELECT COALESCE(SUM(b.quantity), 0) FROM BookingEntity b WHERE b.tripId = :tripId AND b.status = :status")
    long countSeats(@Param("tripId") Long tripId, @Param("status") BookingStatus status);

    @Query("""
        SELECT b FROM BookingEntity b
        WHERE (:skipUser = true OR b.userId = :userId)
          AND (:skipTrip = true OR b.tripId = :tripId)
          AND (:skipStatus = true OR b.status = :status)
        ORDER BY b.bookedAt DESC, b.id DESC
        """)
    List<BookingEntity> findForAdmin(Long userId, Long tripId, BookingStatus status,
                                     boolean skipUser, boolean skipTrip, boolean skipStatus, Pageable page);
    Optional<BookingEntity> findByIdAndUserId(Long id, Long userId);
    List<BookingEntity> findAllByUserIdOrderByBookedAtDescIdDesc(Long userId, Pageable page);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("SELECT b FROM BookingEntity b WHERE b.id = :id")
    Optional<BookingEntity> findByIdForUpdate(@Param("id") Long id);

    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("UPDATE BookingEntity b SET b.status = :status WHERE b.id = :id")
    int updateStatus(@Param("id") Long id, @Param("status") BookingStatus status);

    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query(value = """
        UPDATE bookings SET status = 'REFUND_PENDING', notice_due_at = :due
         WHERE trip_id = :tripId AND status = 'CONFIRMED'
        """, nativeQuery = true)
    int markTripRefundPending(@Param("tripId") Long tripId, @Param("due") java.time.Instant due);

    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query(value = """
        UPDATE bookings SET status = 'REFUNDED', refunded_at = :at
         WHERE id = :id AND status = 'REFUND_PENDING'
        """, nativeQuery = true)
    int markRefunded(@Param("id") Long id, @Param("at") java.time.Instant at);
}
