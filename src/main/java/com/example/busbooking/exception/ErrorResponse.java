package com.example.busbooking.exception;

import com.fasterxml.jackson.annotation.JsonInclude;
import java.time.OffsetDateTime;
import java.util.Map;

public record ErrorResponse(OffsetDateTime timestamp, int status, String error, String message, String path,
                            @JsonInclude(JsonInclude.Include.NON_EMPTY) Map<String, String> details) { }
