package com.example.busbooking.security;

import com.example.busbooking.business.port.repository.UserRepository;

public final class CurrentUserLoader {
    private final UserRepository users;

    public CurrentUserLoader(UserRepository users) { this.users = users; }

    public AuthenticatedPrincipal loadById(Long userId, int tokenVersion) {
        if (userId == null || userId <= 0) { throw new JwtAuthenticationException(); }
        var user = users.findActiveVerifiedPrincipal(userId).orElseThrow(JwtAuthenticationException::new);
        if (user.tokenVersion() != tokenVersion) { throw new JwtAuthenticationException(); }
        return new AuthenticatedPrincipal(user.id(), user.email(), user.role());
    }
}
