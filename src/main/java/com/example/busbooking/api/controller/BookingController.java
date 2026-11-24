package com.example.busbooking.api.controller;

import com.example.busbooking.api.dto.booking.*;
import com.example.busbooking.api.mapper.BookingDtoMapper;
import com.example.busbooking.business.command.PageQuery;
import com.example.busbooking.business.service.BookingService;
import com.example.busbooking.domain.exception.ForbiddenOperationException;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;

import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import java.util.List;

@RestController
@RequestMapping("/api")
@SecurityRequirement(name = "bearerAuth")
public class BookingController {
    private final BookingService bookingService;
    private final BookingDtoMapper mapper;
    private final BookingAdmission admission;

    public BookingController(BookingService bookingService, BookingDtoMapper mapper, BookingAdmission admission) {
        this.bookingService = bookingService;
        this.mapper = mapper;
        this.admission = admission;
    }

    @PostMapping("/bookings")
    public ResponseEntity<BookingResponse> create(@Valid @RequestBody BookingRequest request,
                                                   @RequestHeader(value = "Idempotency-Key", required = false) String key,
                                                   Authentication authentication) {
        Long userId = userId(authentication);
        var booking = admission.run(request.tripId(), () -> bookingService.create(
                userId, request.tripId(), request.passengerName(), request.passengerPhone(), request.quantity(), key));
        return ResponseEntity.status(201).body(mapper.toResponse(booking));
    }

    @GetMapping("/bookings/{bookingId}")
    public BookingResponse get(@PathVariable Long bookingId, Authentication authentication) {
        Long userId = userId(authentication);
        return mapper.toResponse(bookingService.get(userId, isAdmin(authentication), bookingId));
    }

    @DeleteMapping("/bookings/{bookingId}")
    public BookingResponse cancel(@PathVariable Long bookingId, Authentication authentication) {
        Long userId = userId(authentication);
        return mapper.toResponse(bookingService.cancel(userId, isAdmin(authentication), bookingId));
    }

    @GetMapping("/users/me/bookings")
    public List<BookingHistoryResponse> history(Authentication authentication,
                                                @RequestParam(defaultValue = "0") int page,
                                                @RequestParam(defaultValue = "20") int size) {
        var pagination = new PageQuery(page, size);
        return bookingService.history(userId(authentication), pagination.page(), pagination.size()).stream()
                .map(mapper::toHistoryResponse).toList();
    }

    private Long userId(Authentication authentication) {
        if (authentication == null || !authentication.isAuthenticated()) {
            throw new ForbiddenOperationException("Authentication is required");
        }
        try {
            return Long.valueOf(authentication.getName());
        } catch (NumberFormatException ex) {
            throw new ForbiddenOperationException("Authenticated principal must contain a numeric user id");
        }
    }

    private boolean isAdmin(Authentication authentication) {
        return authentication.getAuthorities().stream()
                .anyMatch(a -> "ROLE_ADMIN".equals(a.getAuthority()) || "ADMIN".equals(a.getAuthority())
                        || "ROLE_SUPER_ADMIN".equals(a.getAuthority()) || "SUPER_ADMIN".equals(a.getAuthority()));
    }
}
