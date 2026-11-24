package com.example.busbooking.domain.exception;

public class IdempotencyConflictException extends BusinessException {
    public IdempotencyConflictException() {
        super("This idempotency key is already associated with a different request");
    }
}
