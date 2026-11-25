package com.example.busbooking.business.service;

import com.example.busbooking.domain.exception.InvalidAuthInputException;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.regex.Pattern;

public final class AuthInputPolicy {
    // Deliberately a bounded ASCII email format for this application, not full RFC parsing.
    private static final Pattern EMAIL = Pattern.compile("[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+");
    private static final Pattern PHONE = Pattern.compile("0(?:[35789][0-9]{8}|2[0-9]{9})");

    // shortcut: a short built-in list of the most common 8+ character passwords; load a breach corpus if the threat model grows.
    private static final java.util.Set<String> COMMON_PASSWORDS = java.util.Set.of(
            "password", "password1", "password12", "password123", "password1234", "passw0rd", "p@ssw0rd", "p@ssword",
            "12345678", "123456789", "1234567890", "0123456789", "87654321", "11111111", "00000000", "12341234",
            "qwertyui", "qwerty12", "qwerty123", "qwertyuiop", "1q2w3e4r", "1qaz2wsx", "zaq12wsx", "asdfghjk",
            "abc12345", "abcd1234", "iloveyou", "iloveyou1", "admin123", "administrator", "letmein1", "welcome1",
            "welcome123", "sunshine", "princess", "football", "baseball", "superman", "trustno1", "matkhau123");

    private AuthInputPolicy() { }

    public static String email(String raw) {
        String email = raw == null ? "" : raw.strip().toLowerCase(Locale.ROOT);
        if (email.length() > 100 || !EMAIL.matcher(email).matches()
                || email.substring(0, email.indexOf('@')).length() > 64) {
            throw new InvalidAuthInputException("email", "A valid email of at most 100 characters is required");
        }
        return email;
    }

    public static String fullName(String raw) {
        String name = raw == null ? "" : raw.strip();
        if (name.isBlank() || name.length() > 100 || name.chars().anyMatch(Character::isISOControl)) {
            throw new InvalidAuthInputException("fullName", "Full name must contain 1 to 100 characters");
        }
        return name;
    }

    public static String phone(String raw) {
        String phone = raw == null ? "" : raw.strip();
        if (phone.startsWith("+84")) { phone = "0" + phone.substring(3); }
        if (!PHONE.matcher(phone).matches()) {
            throw new InvalidAuthInputException("phone", "A Vietnamese phone number is required");
        }
        return phone;
    }

    public static void registrationPassword(String password) {
        if (password == null || password.codePointCount(0, password.length()) < 8
                || password.isBlank() || password.getBytes(StandardCharsets.UTF_8).length > 72) {
            throw new InvalidAuthInputException("password", "Password requires at least 8 characters and at most 72 UTF-8 bytes");
        }
        if (COMMON_PASSWORDS.contains(password.toLowerCase(Locale.ROOT))) {
            throw new InvalidAuthInputException("password", "Password is too common; choose a less predictable one");
        }
    }
}
