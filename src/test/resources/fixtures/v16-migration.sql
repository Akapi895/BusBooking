INSERT INTO users (id, full_name, email, password, phone, role_id, status, email_verified)
VALUES (1101, 'Upgrade Fixture', 'upgrade-test@example.com', 'fixture-only', '0901234567',
        (SELECT id FROM roles WHERE name = 'USER'), 'ACTIVE', TRUE);

INSERT INTO locations (id, name, province, address) VALUES
    (1101, 'Upgrade Origin', 'Fixture Province', 'Origin Address'),
    (1102, 'Upgrade Destination', 'Fixture Province', 'Destination Address');
INSERT INTO bus_operators (id, name, address, phone, email, status)
VALUES (1101, 'Upgrade Operator', 'Operator Address', '0901234567', 'operator@example.com', 'ACTIVE');
INSERT INTO routes (id, origin_id, destination_id, estimated_duration_minutes, status)
VALUES (1101, 1101, 1102, 120, 'ACTIVE');
INSERT INTO vehicles (id, operator_id, license_plate, vehicle_type, seat_capacity, status)
VALUES (1101, 1101, 'UPGRADE-TEST', 'BUS', 10, 'ACTIVE');
INSERT INTO trips (id, route_id, vehicle_id, departure_time, arrival_time, price, available_seats, status)
VALUES (1101, 1101, 1101, '2099-01-01 08:00:00', '2099-01-01 10:00:00', 150000, 8, 'SCHEDULED');
INSERT INTO bookings (id, booking_code, user_id, trip_id, passenger_name, passenger_phone,
                      quantity, unit_price, total_amount, status, booked_at)
VALUES (1101, 'V16-FIXTURE', 1101, 1101, 'Upgrade Fixture', '0901234567',
        2, 150000, 300000, 'CONFIRMED', '2098-12-01 08:00:00');
