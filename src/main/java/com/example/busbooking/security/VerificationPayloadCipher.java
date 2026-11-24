package com.example.busbooking.security;

import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.SecureRandom;
import java.util.Arrays;
import java.util.Base64;

public final class VerificationPayloadCipher {
    private static final int NONCE_BYTES = 12;
    private final SecureRandom random = new SecureRandom();
    private final SecretKeySpec key;

    public VerificationPayloadCipher(String secret) {
        byte[] decoded = Base64.getDecoder().decode(secret);
        if (decoded.length != 32) throw new IllegalArgumentException("OTP_OUTBOX_SECRET must encode 32 bytes");
        key = new SecretKeySpec(decoded, "AES");
    }

    public byte[] encrypt(String code, String digest) {
        byte[] nonce = new byte[NONCE_BYTES];
        random.nextBytes(nonce);
        byte[] encrypted = transform(Cipher.ENCRYPT_MODE, nonce, digest, code.getBytes(StandardCharsets.UTF_8));
        byte[] payload = Arrays.copyOf(nonce, nonce.length + encrypted.length);
        System.arraycopy(encrypted, 0, payload, nonce.length, encrypted.length);
        return payload;
    }

    public String decrypt(byte[] payload, String digest) {
        byte[] nonce = Arrays.copyOf(payload, NONCE_BYTES);
        return new String(transform(Cipher.DECRYPT_MODE, nonce, digest,
                Arrays.copyOfRange(payload, NONCE_BYTES, payload.length)), StandardCharsets.UTF_8);
    }

    private byte[] transform(int mode, byte[] nonce, String digest, byte[] data) {
        try {
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(mode, key, new GCMParameterSpec(128, nonce));
            cipher.updateAAD(digest.getBytes(StandardCharsets.US_ASCII));
            return cipher.doFinal(data);
        } catch (GeneralSecurityException exception) {
            throw new IllegalStateException("Unable to process encrypted verification payload", exception);
        }
    }
}
