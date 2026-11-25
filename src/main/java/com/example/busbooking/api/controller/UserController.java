package com.example.busbooking.api.controller;

import com.example.busbooking.api.dto.user.*;
import com.example.busbooking.api.mapper.UserDtoMapper;
import com.example.busbooking.business.service.UserService;
import com.example.busbooking.security.AuthenticatedPrincipal;
import com.example.busbooking.security.ratelimit.AuthRateLimitProperties;
import com.example.busbooking.security.ratelimit.AuthRateLimiter;
import com.example.busbooking.security.ratelimit.LoginThrottledException;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.responses.*;
import io.swagger.v3.oas.annotations.media.*;
import com.example.busbooking.exception.ErrorResponse;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import org.springframework.http.*;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/users/me")
@SecurityRequirement(name = "bearerAuth")
@Tag(name = "User profile")
@ApiResponses({
        @ApiResponse(responseCode = "400", description = "Invalid profile fields", content = @Content(schema = @Schema(implementation = ErrorResponse.class))),
        @ApiResponse(responseCode = "401", description = "Authentication required", content = @Content(schema = @Schema(implementation = ErrorResponse.class))),
        @ApiResponse(responseCode = "500", description = "Internal error", content = @Content(schema = @Schema(implementation = ErrorResponse.class)))
})
public class UserController {
    private static final org.slf4j.Logger AUDIT = org.slf4j.LoggerFactory.getLogger("security.audit");
    private final UserService users;
    private final UserDtoMapper mapper;
    private final AuthRateLimiter limiter;
    public UserController(UserService users, UserDtoMapper mapper, AuthRateLimiter limiter) {
        this.users = users; this.mapper = mapper; this.limiter = limiter;
    }

    @GetMapping
    @Operation(summary = "Read your own profile")
    public ResponseEntity<UserResponse> profile(@AuthenticationPrincipal AuthenticatedPrincipal principal) {
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(mapper.user(users.getProfile(principal.userId())));
    }

    @PutMapping
    @Operation(summary = "Replace your full name and Vietnamese contact phone")
    public ResponseEntity<UserResponse> update(@AuthenticationPrincipal AuthenticatedPrincipal principal,
                                               @Valid @RequestBody UpdateProfileRequest request) {
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(mapper.user(users.updateProfile(principal.userId(), mapper.command(request))));
    }

    @PutMapping("/password")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    @ApiResponse(responseCode = "429", description = "Too many attempts", content = @Content(schema = @Schema(implementation = ErrorResponse.class)))
    @Operation(summary = "Change your password; every existing access token, including this one, is revoked")
    public ResponseEntity<Void> changePassword(@AuthenticationPrincipal AuthenticatedPrincipal principal,
                                               @Valid @RequestBody ChangePasswordRequest request) {
        // Same per-account quota as login, so a stolen token cannot be used to guess the current password.
        var decision = limiter.consume("change-password:" + principal.userId(), AuthRateLimitProperties.LOGIN_ACCOUNT);
        if (!decision.allowed()) { throw new LoginThrottledException(decision.retryAfterSeconds()); }
        users.changePassword(principal.userId(), request.currentPassword(), request.newPassword());
        AUDIT.info("event=password_changed userId={}", principal.userId());
        return ResponseEntity.noContent().cacheControl(CacheControl.noStore()).build();
    }
}
