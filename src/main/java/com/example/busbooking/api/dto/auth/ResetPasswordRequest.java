package com.example.busbooking.api.dto.auth;

import com.example.busbooking.api.validation.AuthField;
import com.fasterxml.jackson.annotation.JsonAnySetter;
import io.swagger.v3.oas.annotations.media.Schema;

@Schema(additionalProperties = Schema.AdditionalPropertiesValue.FALSE)
public record ResetPasswordRequest(
        @AuthField(AuthField.Kind.EMAIL) String email,
        @jakarta.validation.constraints.NotNull
        @jakarta.validation.constraints.Pattern(regexp = "[0-9]{6}", message = "Code must contain six digits") String code,
        @Schema(format = "password", accessMode = Schema.AccessMode.WRITE_ONLY)
        @AuthField(AuthField.Kind.REGISTER_PASSWORD) String newPassword) {
    @JsonAnySetter
    public void rejectUnknown(String name, Object value) { throw new IllegalArgumentException("Unsupported request field"); }

    @Override public String toString() { return "ResetPasswordRequest[REDACTED]"; }
}
