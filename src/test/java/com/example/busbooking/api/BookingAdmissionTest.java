package com.example.busbooking.api;

import com.example.busbooking.api.controller.BookingAdmission;
import com.example.busbooking.domain.exception.BookingBusyException;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.*;

class BookingAdmissionTest {
    @Test
    void totalCapRejectsAnotherTripOnceHotTripsHoldEveryPermit() {
        var admission = new BookingAdmission(8, 2);
        // Nested calls keep the outer bookings in flight, like two trips waiting on their row locks.
        String result = admission.run(1, () -> admission.run(2, () -> {
            assertThatThrownBy(() -> admission.run(3, () -> "third")).isInstanceOf(BookingBusyException.class);
            return "second";
        }));
        assertThat(result).isEqualTo("second");
        assertThat(admission.run(3, () -> "after")).isEqualTo("after");
    }

    @Test
    void perTripRejectionReturnsItsTotalPermit() {
        var admission = new BookingAdmission(1, 2);
        admission.run(1, () -> {
            assertThatThrownBy(() -> admission.run(1, () -> "same trip")).isInstanceOf(BookingBusyException.class);
            // The rejected same-trip attempt must not leak the second total permit.
            return admission.run(2, () -> "other trip");
        });
        assertThat(admission.run(1, () -> "free")).isEqualTo("free");
    }

    @Test
    void failingBookingReleasesBothLimits() {
        var admission = new BookingAdmission(1, 1);
        assertThatThrownBy(() -> admission.run(1, () -> { throw new IllegalStateException("db error"); }))
                .isInstanceOf(IllegalStateException.class);
        assertThat(admission.run(1, () -> "retry")).isEqualTo("retry");
    }
}
