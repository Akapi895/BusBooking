package com.example.busbooking.domain.model;

import com.example.busbooking.domain.enums.RoleName;

public record RoleChanged(long actorId, long targetId, RoleName previousRole, RoleName newRole) { }
