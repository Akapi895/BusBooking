package com.example.busbooking.business;

import com.example.busbooking.business.service.AuthInputPolicy;
import com.example.busbooking.domain.exception.InvalidAuthInputException;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;

class AuthInputPolicyTest {
    @Test
    void rejectsCommonPasswordsRegardlessOfCaseButAcceptsOthers() {
        for (String common : new String[] {"Password123", "PASSWORD1", "12345678", "qwerty123"}) {
            assertThatThrownBy(() -> AuthInputPolicy.registrationPassword(common))
                    .isInstanceOf(InvalidAuthInputException.class).hasMessageContaining("too common");
        }
        assertThatCode(() -> AuthInputPolicy.registrationPassword("BusTrip2026")).doesNotThrowAnyException();
    }
}
