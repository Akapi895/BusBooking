package com.example.busbooking.domain.enums;

public enum BookingStatus {
    CONFIRMED,
    CANCELLED,
    /** The trip was cancelled; the customer is owed a refund. */
    REFUND_PENDING,
    REFUNDED
}
