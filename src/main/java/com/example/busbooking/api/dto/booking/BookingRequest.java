package com.example.busbooking.api.dto.booking;

import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;

public record BookingRequest(
        @NotNull @Positive Long tripId,
        @NotBlank @Size(max = 100) String passengerName,
        @NotBlank @Size(max = 20) String passengerPhone,
        @Min(1) int quantity
) {
}
