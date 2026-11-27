package com.example.busbooking.business.port.repository;

import com.example.busbooking.domain.model.User;
import com.example.busbooking.domain.enums.RoleName;
import java.util.Optional;

public interface UserRepository {
    record Principal(long id, String email, RoleName role, int tokenVersion) {}

    Optional<Principal> findActiveVerifiedPrincipal(Long id);
    Optional<User> findById(Long id);
    Optional<User> findByEmail(String email);
    boolean existsByEmail(String email);
    User save(User user);
    Optional<User> updateProfile(Long userId, String fullName, String phone);
    Optional<User> findSuperAdmin();
    void revokeTokens(Long userId);
    /** Stores a new hash and revokes earlier tokens; false when the account is no longer active and verified. */
    boolean changePassword(Long userId, String passwordHash);
}
