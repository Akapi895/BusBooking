CREATE INDEX idx_trips_bookable_departure ON trips (departure_time, id)
    WHERE status = 'SCHEDULED' AND available_seats > 0;
CREATE INDEX idx_trips_bookable_route_departure ON trips (route_id, departure_time, id)
    WHERE status = 'SCHEDULED' AND available_seats > 0;
CREATE INDEX idx_bookings_user_booked_at ON bookings (user_id, booked_at DESC, id DESC);
