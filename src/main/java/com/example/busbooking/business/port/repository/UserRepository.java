package com.example.busbooking.business.port.repository;

import com.example.busbooking.domain.model.User;
import com.example.busbooking.domain.enums.RoleName;
import java.util.Optional;

public interface UserRepository {
    record Principal(long id, String email, RoleName role) {}

    Optional<Principal> findActiveVerifiedPrincipal(Long id);
    Optional<User> findById(Long id);
    Optional<User> findByEmail(String email);
    boolean existsByEmail(String email);
    User save(User user);
    Optional<User> updateProfile(Long userId, String fullName, String phone);
    Optional<User> findSuperAdmin();
}
