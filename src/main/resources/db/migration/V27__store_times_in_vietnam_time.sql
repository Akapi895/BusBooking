-- Wall-clock columns (TIMESTAMP without time zone) now hold Vietnam time, the zone the app works in.
-- Until now Hibernate wrote them in UTC (hibernate.jdbc.time_zone=UTC) while native SQL compared them
-- with Vietnam time, so a trip departing within the next 7 hours could not be booked.
-- trips.created_at comes from the column default in the Vietnam session time zone and is already right.
UPDATE trips
SET departure_time = departure_time + interval '7 hours',
    arrival_time   = arrival_time + interval '7 hours';

UPDATE bookings
SET booked_at       = booked_at + interval '7 hours',
    hold_expires_at = hold_expires_at + interval '7 hours';

UPDATE bus_operators SET created_at = created_at + interval '7 hours';
UPDATE vehicles SET created_at = created_at + interval '7 hours';

-- Show TIMESTAMPTZ columns in Vietnam time in psql or the Neon SQL editor too (the app sets it per connection).
DO $$
BEGIN
    EXECUTE format('ALTER DATABASE %I SET timezone TO %L', current_database(), 'Asia/Ho_Chi_Minh');
EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'Not the database owner: default time zone left unchanged';
END $$;
