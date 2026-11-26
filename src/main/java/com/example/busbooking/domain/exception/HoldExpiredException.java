package com.example.busbooking.domain.exception;

public class HoldExpiredException extends RuntimeException {
    public HoldExpiredException() {
        super("The seat hold has expired; book again");
    }
}
