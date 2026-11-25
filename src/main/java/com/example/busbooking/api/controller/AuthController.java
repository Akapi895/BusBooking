package com.example.busbooking.api.controller;

import com.example.busbooking.api.dto.auth.*;
import com.example.busbooking.api.dto.user.UserResponse;
import com.example.busbooking.api.mapper.AuthDtoMapper;
import com.example.busbooking.business.service.AuthInputPolicy;
import com.example.busbooking.business.service.AuthService;
import com.example.busbooking.business.service.EmailVerificationService;
import com.example.busbooking.business.service.PasswordResetService;
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
import com.example.busbooking.domain.exception.InvalidAuthInputException;
import com.example.busbooking.domain.exception.InvalidVerificationCodeException;
import com.example.busbooking.domain.exception.InvalidCredentialsException;
import jakarta.validation.Valid;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import org.springframework.http.*;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/auth")
@Tag(name = "Authentication", description = "Email OTP registration and JWT access")
@ApiResponses({
        @ApiResponse(responseCode = "400", description = "Invalid request or verification code", content = @Content(schema = @Schema(implementation = ErrorResponse.class))),
        @ApiResponse(responseCode = "401", description = "Authentication failed", content = @Content(schema = @Schema(implementation = ErrorResponse.class))),
        @ApiResponse(responseCode = "429", description = "Request limit or resend cooldown", content = @Content(schema = @Schema(implementation = ErrorResponse.class))),
        @ApiResponse(responseCode = "500", description = "Internal error", content = @Content(schema = @Schema(implementation = ErrorResponse.class)))
})
public class AuthController {
    private static final org.slf4j.Logger AUDIT = org.slf4j.LoggerFactory.getLogger("security.audit");
    private final AuthService auth;
    private final EmailVerificationService verification;
    private final AuthDtoMapper mapper;
    private final AuthRateLimiter limiter;
    private final PasswordResetService passwordReset;

    public AuthController(AuthService auth, EmailVerificationService verification, AuthDtoMapper mapper,
                          AuthRateLimiter limiter, PasswordResetService passwordReset) {
        this.auth = auth;
        this.verification = verification;
        this.mapper = mapper;
        this.limiter = limiter;
        this.passwordReset = passwordReset;
    }

    @PostMapping("/register")
    @ResponseStatus(HttpStatus.CREATED)
    @ApiResponses({
            @ApiResponse(responseCode = "409", description = "Email already registered", content = @Content(schema = @Schema(implementation = ErrorResponse.class))),
            @ApiResponse(responseCode = "503", description = "Verification request temporarily unavailable", content = @Content(schema = @Schema(implementation = ErrorResponse.class)))
    })
    @Operation(summary = "Register a USER and request an email verification code")
    public ResponseEntity<UserResponse> register(@Valid @RequestBody RegisterRequest request) {
        return ResponseEntity.status(HttpStatus.CREATED).cacheControl(CacheControl.noStore())
                .body(mapper.user(auth.register(mapper.command(request))));
    }

    @PostMapping("/login")
    @Operation(summary = "Login after email verification and receive an access JWT")
    public ResponseEntity<LoginResponse> login(@Valid @RequestBody LoginRequest request) {
        String account = throttleAccount(request.email());
        try {
            var result = auth.login(mapper.command(request));
            AUDIT.info("event=login_succeeded userId={}", result.user().id());
            return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(mapper.login(result));
        } catch (InvalidCredentialsException failed) {
            AUDIT.warn("event=login_failed account={}", account);
            throw failed;
        }
    }

    @PostMapping("/verify-email")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    @Operation(summary = "Verify a six-digit email code; does not issue a JWT")
    public ResponseEntity<Void> verify(@Valid @RequestBody VerifyEmailRequest request) {
        verification.verify(mapper.command(request));
        return ResponseEntity.noContent().cacheControl(CacheControl.noStore()).build();
    }

    @PostMapping("/resend-verification")
    @ResponseStatus(HttpStatus.ACCEPTED)
    @ApiResponse(responseCode = "503", description = "Verification request temporarily unavailable", content = @Content(schema = @Schema(implementation = ErrorResponse.class)))
    @Operation(summary = "Request another code if the account is eligible")
    public ResponseEntity<MessageResponse> resend(@Valid @RequestBody ResendVerificationRequest request) {
        verification.resend(request.email());
        return ResponseEntity.accepted().cacheControl(CacheControl.noStore())
                .body(new MessageResponse("If the account is eligible, a verification email has been requested"));
    }

    @PostMapping("/forgot-password")
    @ResponseStatus(HttpStatus.ACCEPTED)
    @ApiResponse(responseCode = "503", description = "SMTP unavailable", content = @Content(schema = @Schema(implementation = ErrorResponse.class)))
    @Operation(summary = "Email a password-reset code if the account is eligible")
    public ResponseEntity<MessageResponse> forgotPassword(@Valid @RequestBody ResendVerificationRequest request) {
        passwordReset.request(request.email());
        return ResponseEntity.accepted().cacheControl(CacheControl.noStore())
                .body(new MessageResponse("If the account is eligible, a password reset email has been sent"));
    }

    @PostMapping("/reset-password")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    @Operation(summary = "Set a new password with the emailed code; every existing access token is revoked")
    public ResponseEntity<Void> resetPassword(@Valid @RequestBody ResetPasswordRequest request) {
        try {
            passwordReset.reset(request.email(), request.code(), request.newPassword());
        } catch (InvalidVerificationCodeException failed) {
            AUDIT.warn("event=password_reset_failed account={}", accountId(request.email()));
            throw failed;
        }
        AUDIT.info("event=password_reset account={}", accountId(request.email()));
        return ResponseEntity.noContent().cacheControl(CacheControl.noStore()).build();
    }

    @PostMapping("/logout")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    @SecurityRequirement(name = "bearerAuth")
    @Operation(summary = "Revoke every access token issued to the current account")
    public ResponseEntity<Void> logout(@AuthenticationPrincipal AuthenticatedPrincipal principal) {
        auth.logout(principal.userId());
        AUDIT.info("event=logout userId={}", principal.userId());
        return ResponseEntity.noContent().cacheControl(CacheControl.noStore()).build();
    }

    @GetMapping("/me")
    @SecurityRequirement(name = "bearerAuth")
    @Operation(summary = "Read the current authenticated account")
    public ResponseEntity<CurrentUserResponse> me(@AuthenticationPrincipal AuthenticatedPrincipal principal) {
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(mapper.currentUser(auth.currentUser(principal.userId())));
    }

    // The per-IP filter cannot stop one account being guessed from many addresses.
    private String throttleAccount(String rawEmail) {
        String email;
        try { email = AuthInputPolicy.email(rawEmail); }
        catch (InvalidAuthInputException invalid) { return "invalid"; } // login rejects it without touching an account
        String key = sha256(email);
        var decision = limiter.consume(key, AuthRateLimitProperties.LOGIN_ACCOUNT);
        if (!decision.allowed()) {
            AUDIT.warn("event=login_throttled account={}", key.substring(0, 12));
            throw new LoginThrottledException(decision.retryAfterSeconds());
        }
        return key.substring(0, 12);
    }

    // Pseudonymous account reference for the audit log: correlates events without storing the email.
    private static String accountId(String rawEmail) {
        try { return sha256(AuthInputPolicy.email(rawEmail)).substring(0, 12); }
        catch (InvalidAuthInputException invalid) { return "invalid"; }
    }

    // Keeps raw emails out of limiter keys stored in Redis.
    private static String sha256(String value) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        }
    }
}
