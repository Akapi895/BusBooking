package com.example.busbooking.api.dto.user;

import com.example.busbooking.api.validation.AuthField;
import com.fasterxml.jackson.annotation.JsonAnySetter;
import io.swagger.v3.oas.annotations.media.Schema;

@Schema(additionalProperties = Schema.AdditionalPropertiesValue.FALSE)
public record ChangePasswordRequest(
        @Schema(format = "password", accessMode = Schema.AccessMode.WRITE_ONLY)
        @AuthField(AuthField.Kind.LOGIN_PASSWORD) String currentPassword,
        @Schema(format = "password", accessMode = Schema.AccessMode.WRITE_ONLY)
        @AuthField(AuthField.Kind.REGISTER_PASSWORD) String newPassword) {
    @JsonAnySetter
    public void rejectUnknown(String name, Object value) { throw new IllegalArgumentException("Unsupported request field"); }

    @Override public String toString() { return "ChangePasswordRequest[REDACTED]"; }
}
