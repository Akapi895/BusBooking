CREATE EXTENSION IF NOT EXISTS btree_gist;
DO $$
DECLARE
    conflict RECORD;
BEGIN
    SELECT a.vehicle_id, a.id AS first_trip, b.id AS second_trip
      INTO conflict
      FROM trips a
      JOIN trips b ON a.vehicle_id = b.vehicle_id AND a.id < b.id
     WHERE a.status <> 'CANCELLED' AND b.status <> 'CANCELLED'
       AND tsrange(a.departure_time, a.arrival_time) && tsrange(b.departure_time, b.arrival_time)
     LIMIT 1;
    IF FOUND THEN
        RAISE EXCEPTION 'Resolve overlapping trips % and % for vehicle % before applying V18',
            conflict.first_trip, conflict.second_trip, conflict.vehicle_id;
    END IF;
END $$;
ALTER TABLE trips ADD CONSTRAINT trips_vehicle_schedule_no_overlap
    EXCLUDE USING gist (vehicle_id WITH =, tsrange(departure_time, arrival_time) WITH &&)
    WHERE (status <> 'CANCELLED');
