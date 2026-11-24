CREATE INDEX idx_bookings_trip_status ON bookings (trip_id, status);

CREATE INDEX idx_trips_scheduled_departure ON trips (departure_time)
    WHERE status = 'SCHEDULED';
CREATE INDEX idx_trips_in_progress_arrival ON trips (arrival_time)
    WHERE status = 'IN_PROGRESS';
