package com.example.busbooking.domain.enums;

public enum BookingStatus {
    /** Seats are held for the customer until they confirm or the hold expires. */
    HELD,
    CONFIRMED,
    /** The hold lapsed unconfirmed; its seats went back to the trip. */
    EXPIRED,
    CANCELLED,
    /** The trip was cancelled; the customer is owed a refund. */
    REFUND_PENDING,
    REFUNDED
}
