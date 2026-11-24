package com.example.busbooking.business.command;

import com.example.busbooking.domain.exception.BusinessException;

public record PageQuery(int page, int size) {
    public PageQuery {
        if (page < 0 || size < 1 || size > 100 || (long) page * size > Integer.MAX_VALUE) {
            throw new BusinessException("Use a non-negative page and a size between 1 and 100");
        }
    }
}
