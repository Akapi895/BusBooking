package com.example.busbooking.business.service;

import com.example.busbooking.business.command.UpdateProfileCommand;
import com.example.busbooking.business.port.repository.UserRepository;
import com.example.busbooking.business.port.security.PasswordHasher;
import com.example.busbooking.business.result.AuthenticatedUser;
import com.example.busbooking.domain.enums.UserStatus;
import com.example.busbooking.domain.exception.InvalidAuthInputException;
import com.example.busbooking.domain.exception.InvalidCredentialsException;

public class UserService {
    private final UserRepository users;
    private final PasswordHasher passwords;
    public UserService(UserRepository users, PasswordHasher passwords) { this.users = users; this.passwords = passwords; }

    public AuthenticatedUser getProfile(Long userId) {
        if (userId == null || userId <= 0) { throw new InvalidCredentialsException(); }
        var user = users.findById(userId).orElseThrow(InvalidCredentialsException::new);
        if (user.getStatus() != UserStatus.ACTIVE || !user.isEmailVerified()
                || user.getRole() == null || user.getRole().getName() == null) {
            throw new InvalidCredentialsException();
        }
        return AuthenticatedUser.from(user);
    }

    public AuthenticatedUser updateProfile(Long userId, UpdateProfileCommand command) {
        if (command == null) { throw new InvalidAuthInputException("request", "Profile data is required"); }
        String name = AuthInputPolicy.fullName(command.fullName());
        String phone = AuthInputPolicy.phone(command.phone());
        getProfile(userId);
        return users.updateProfile(userId, name, phone).map(AuthenticatedUser::from)
                .orElseThrow(InvalidCredentialsException::new);
    }

    /** Changes the password and logs out every existing session, including the caller's. */
    public void changePassword(Long userId, String currentPassword, String newPassword) {
        AuthInputPolicy.registrationPassword(newPassword);
        getProfile(userId);
        var user = users.findById(userId).orElseThrow(InvalidCredentialsException::new);
        if (currentPassword == null || !passwords.matches(currentPassword, user.getPasswordHash())) {
            throw new InvalidAuthInputException("currentPassword", "Current password is incorrect");
        }
        if (newPassword.equals(currentPassword)) {
            throw new InvalidAuthInputException("newPassword", "New password must differ from the current password");
        }
        if (!users.changePassword(userId, passwords.hash(newPassword))) { throw new InvalidCredentialsException(); }
    }
}
