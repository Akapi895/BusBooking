package com.example.busbooking.security;

import com.example.busbooking.business.port.repository.UserRepository;
import com.example.busbooking.domain.enums.*;
import com.example.busbooking.domain.model.*;
import org.junit.jupiter.api.Test;
import java.util.Optional;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class CurrentUserLoaderTest {
    private final UserRepository users = mock(UserRepository.class);
    private final CurrentUserLoader loader = new CurrentUserLoader(users);

    @Test
    void loadsOnlySafeIdentityAndReadsUpdatedRoleEachTime() {
        when(users.findActiveVerifiedPrincipal(42L)).thenReturn(Optional.of(principal(RoleName.USER)))
                .thenReturn(Optional.of(principal(RoleName.ADMIN)));
        var first = loader.loadById(42L, 0);
        assertThat(first.getName()).isEqualTo("42");
        assertThat(first.email()).isEqualTo("hoang@example.com");
        assertThat(first.role()).isEqualTo(RoleName.USER);
        assertThat(first.toString()).doesNotContain("hash-fixture");
        assertThat(loader.loadById(42L, 0).role()).isEqualTo(RoleName.ADMIN);
        verify(users, times(2)).findActiveVerifiedPrincipal(42L);
    }

    @Test
    void deniesDeletedInactiveUnverifiedOrMissingRoleAccounts() {
        when(users.findActiveVerifiedPrincipal(42L)).thenReturn(Optional.empty());
        assertThatThrownBy(() -> loader.loadById(42L, 0)).isInstanceOf(JwtAuthenticationException.class);
    }

    @Test
    void deniesInvalidIdsBeforeAccessingRepository() {
        for (Long id : new Long[] {null, 0L, -1L}) {
            assertThatThrownBy(() -> loader.loadById(id, 0)).isInstanceOf(JwtAuthenticationException.class);
        }
        verifyNoInteractions(users);
    }

    @Test
    void databaseOutageIsNotDisguisedAsInvalidAuthentication() {
        when(users.findActiveVerifiedPrincipal(42L)).thenThrow(new IllegalStateException("database unavailable"));
        assertThatThrownBy(() -> loader.loadById(42L, 0)).isInstanceOf(IllegalStateException.class)
                .hasMessage("database unavailable");
    }

    private UserRepository.Principal principal(RoleName role) {
        return new UserRepository.Principal(42L, "hoang@example.com", role, 0);
    }
}
