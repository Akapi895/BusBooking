-- Demo catalogue: locations, bus operators, routes, vehicles and trips. No accounts, no bookings.
-- The single source of demo data, loaded by Flyway where its location is enabled:
--   dev profile      application-dev.properties (together with db/seed for demo accounts)
--   Render (prod)    SPRING_FLYWAY_LOCATIONS in render.yaml
-- Repeatable: Flyway re-runs it whenever this file changes, and every insert skips rows that exist.
-- Trips are generated relative to the day it runs: 14 days back to 60 days ahead.
-- Flyway runs repeatables by description, so "demo catalogue" runs before "dev seed data".

-- Stable pseudo-random number in [0, n) for a key, so reruns pick the same values.
CREATE OR REPLACE FUNCTION pg_temp.h(key text, n integer) RETURNS integer
    LANGUAGE sql IMMUTABLE AS $$ SELECT (abs(hashtext(key)::bigint) % n)::integer $$;

-- Wall-clock columns (TIMESTAMP) hold Vietnam time, like the app (see V27).
-- utc()/utc_now() keep their old names so the rest of the script is unchanged; both are Vietnam time now.
CREATE OR REPLACE FUNCTION pg_temp.utc(vn_local timestamp) RETURNS timestamp
    LANGUAGE sql IMMUTABLE AS $$ SELECT vn_local $$;
CREATE OR REPLACE FUNCTION pg_temp.utc_now() RETURNS timestamp
    LANGUAGE sql STABLE AS $$ SELECT now() AT TIME ZONE 'Asia/Ho_Chi_Minh' $$;
CREATE OR REPLACE FUNCTION pg_temp.vn_today() RETURNS date
    LANGUAGE sql STABLE AS $$ SELECT (now() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date $$;

-- ---------- Locations (one main coach station per city) ----------
CREATE TEMP TABLE seed_locations (name, province, address, plate_code) ON COMMIT DROP AS VALUES
    ('Hà Nội', 'Hà Nội', 'Bến xe Mỹ Đình, 20 Phạm Hùng, Nam Từ Liêm', '29'),
    ('TP. Hồ Chí Minh', 'TP. Hồ Chí Minh', 'Bến xe Miền Đông mới, 501 Hoàng Hữu Nam, TP. Thủ Đức', '51'),
    ('Đà Nẵng', 'Đà Nẵng', 'Bến xe Trung tâm Đà Nẵng, 201 Tôn Đức Thắng, Liên Chiểu', '43'),
    ('Huế', 'Thừa Thiên Huế', 'Bến xe phía Nam, 97 An Dương Vương', '75'),
    ('Hải Phòng', 'Hải Phòng', 'Bến xe Niệm Nghĩa, 278 Trần Nguyên Hãn, Lê Chân', '15'),
    ('Hạ Long', 'Quảng Ninh', 'Bến xe Bãi Cháy, Đường 279, Giếng Đáy', '14'),
    ('Ninh Bình', 'Ninh Bình', 'Bến xe Ninh Bình, 207 Lê Đại Hành', '35'),
    ('Sapa', 'Lào Cai', 'Bến xe Sapa, Đường Điện Biên Phủ', '24'),
    ('Vinh', 'Nghệ An', 'Bến xe Bắc Vinh, Đường Đặng Thai Mai', '37'),
    ('Nha Trang', 'Khánh Hòa', 'Bến xe phía Nam, Đường 23 Tháng 10, Vĩnh Trung', '79'),
    ('Đà Lạt', 'Lâm Đồng', 'Bến xe liên tỉnh Đà Lạt, 1 Tô Hiến Thành', '49'),
    ('Quy Nhơn', 'Bình Định', 'Bến xe Quy Nhơn, 71 Tây Sơn', '77'),
    ('Buôn Ma Thuột', 'Đắk Lắk', 'Bến xe phía Bắc, 71 Nguyễn Chí Thanh', '47'),
    ('Cần Thơ', 'Cần Thơ', 'Bến xe Trung tâm Cần Thơ, Quốc lộ 1A, Cái Răng', '65'),
    ('Vũng Tàu', 'Bà Rịa - Vũng Tàu', 'Bến xe Vũng Tàu, 192 Nam Kỳ Khởi Nghĩa', '72'),
    ('Phan Thiết', 'Bình Thuận', 'Bến xe Bắc Bình Thuận, Quốc lộ 1A, Phú Long', '86');

-- Reuse a city that already exists under the same name instead of listing it twice.
INSERT INTO locations (name, province, address)
SELECT s.name, s.province, s.address
FROM seed_locations s
WHERE NOT EXISTS (SELECT 1 FROM locations l WHERE lower(l.name) = lower(s.name));

-- ---------- Bus operators ----------
CREATE TEMP TABLE seed_operators (ord, name, address, phone, email) ON COMMIT DROP AS VALUES
    (0, 'Phương Trang', '80 Trần Hưng Đạo, Quận 1, TP. Hồ Chí Minh', '02838386852', 'lienhe@phuongtrang.busbooking.local'),
    (1, 'Hoàng Long', '28 Trần Nhật Duật, Hoàn Kiếm, Hà Nội', '02253920920', 'lienhe@hoanglong.busbooking.local'),
    (2, 'Sao Việt', '17 Phạm Hùng, Nam Từ Liêm, Hà Nội', '0971066699', 'lienhe@saoviet.busbooking.local'),
    (3, 'Thành Bưởi', '266 Lê Hồng Phong, Quận 5, TP. Hồ Chí Minh', '02838309988', 'lienhe@thanhbuoi.busbooking.local'),
    (4, 'Hưng Long', '12 Nguyễn Tri Phương, Huế', '0905112233', 'lienhe@hunglong.busbooking.local'),
    (5, 'Kumho Samco', '292 Đinh Bộ Lĩnh, Bình Thạnh, TP. Hồ Chí Minh', '02835112112', 'lienhe@kumhosamco.busbooking.local'),
    (6, 'Hà Sơn Hải Vân', '41 Quang Trung, Hoàn Kiếm, Hà Nội', '02437770777', 'lienhe@hasonhaivan.busbooking.local'),
    (7, 'Mai Linh Express', '64 Hai Bà Trưng, Quận 1, TP. Hồ Chí Minh', '02839393939', 'lienhe@mailinh.busbooking.local'),
    (8, 'Tâm Hạnh', '18 Ngô Gia Tự, Nha Trang', '0913456789', 'lienhe@tamhanh.busbooking.local'),
    (9, 'Văn Minh', '35 Nguyễn Văn Linh, Đà Nẵng', '0935667788', 'lienhe@vanminh.busbooking.local'),
    (10, 'Inter Bus Lines', '9 Lê Lợi, Quy Nhơn', '0987654321', 'lienhe@interbus.busbooking.local'),
    (11, 'Long Vân', '102 Phan Bội Châu, Buôn Ma Thuột', '0389123456', 'lienhe@longvan.busbooking.local');

INSERT INTO bus_operators (name, address, phone, email, status)
SELECT name, address, phone, email, 'ACTIVE' FROM seed_operators
ON CONFLICT DO NOTHING;

-- ---------- Routes: 20 corridors, each run in both directions ----------
CREATE TEMP TABLE seed_corridors (a, b, minutes) ON COMMIT DROP AS VALUES
    ('Hà Nội', 'Hải Phòng', 120), ('Hà Nội', 'Hạ Long', 180), ('Hà Nội', 'Ninh Bình', 120),
    ('Hà Nội', 'Sapa', 330), ('Hà Nội', 'Vinh', 330), ('Hà Nội', 'Huế', 780),
    ('Hà Nội', 'Đà Nẵng', 900), ('Vinh', 'Huế', 420), ('Huế', 'Đà Nẵng', 150),
    ('Đà Nẵng', 'Quy Nhơn', 330), ('Đà Nẵng', 'Nha Trang', 720), ('TP. Hồ Chí Minh', 'Đà Nẵng', 1080),
    ('TP. Hồ Chí Minh', 'Đà Lạt', 420), ('TP. Hồ Chí Minh', 'Nha Trang', 540), ('TP. Hồ Chí Minh', 'Vũng Tàu', 150),
    ('TP. Hồ Chí Minh', 'Phan Thiết', 240), ('TP. Hồ Chí Minh', 'Cần Thơ', 210), ('TP. Hồ Chí Minh', 'Buôn Ma Thuột', 480),
    ('TP. Hồ Chí Minh', 'Quy Nhơn', 690), ('Nha Trang', 'Đà Lạt', 240);

CREATE TEMP TABLE seed_dirs ON COMMIT DROP AS
SELECT row_number() OVER (ORDER BY x.origin, x.dest)::integer AS dir_no,
       x.origin, x.dest, x.minutes, so.plate_code,
       (SELECT min(id) FROM locations l WHERE lower(l.name) = lower(x.origin)) AS origin_id,
       (SELECT min(id) FROM locations l WHERE lower(l.name) = lower(x.dest)) AS dest_id
FROM (SELECT a AS origin, b AS dest, minutes FROM seed_corridors
      UNION ALL
      SELECT b, a, minutes FROM seed_corridors) x
JOIN seed_locations so ON so.name = x.origin;

INSERT INTO routes (origin_id, destination_id, estimated_duration_minutes, status)
SELECT origin_id, dest_id, minutes, 'ACTIVE' FROM seed_dirs
ON CONFLICT (origin_id, destination_id) DO NOTHING;

-- ---------- Vehicles ----------
-- One vehicle per (direction, daily slot, day parity): a coach runs the same slot every other
-- day, which keeps every vehicle clear of the no-overlap rule (longest route is under 19 h).
CREATE TEMP TABLE seed_vehicle_types (type_name, capacity, price_factor) ON COMMIT DROP AS VALUES
    ('Giường nằm 40 chỗ', 40, 1.0), ('Giường nằm 34 phòng', 34, 1.2), ('Limousine 22 phòng', 22, 1.5),
    ('Limousine 9 chỗ', 9, 1.3), ('Ghế ngồi 29 chỗ', 29, 0.75);

CREATE TEMP TABLE seed_vehicles ON COMMIT DROP AS
SELECT d.dir_no, k.slot, p.parity,
       d.plate_code || 'B' || (90000 + (d.dir_no - 1) * 12 + k.slot * 2 + p.parity + 1)::text AS plate,
       t.type_name, t.capacity, t.price_factor,
       (SELECT name FROM seed_operators o WHERE o.ord = pg_temp.h('op:' || d.dir_no || ':' || k.slot, 12)) AS operator_name
FROM seed_dirs d
CROSS JOIN generate_series(0, 5) AS k(slot)
CROSS JOIN generate_series(0, 1) AS p(parity)
JOIN seed_vehicle_types t ON t.type_name = CASE
    WHEN d.minutes <= 300 THEN (ARRAY['Limousine 9 chỗ', 'Ghế ngồi 29 chỗ', 'Limousine 22 phòng', 'Giường nằm 40 chỗ'])
        [1 + pg_temp.h('vt:' || d.dir_no || ':' || k.slot, 4)]
    ELSE (ARRAY['Giường nằm 40 chỗ', 'Giường nằm 34 phòng', 'Limousine 22 phòng'])
        [1 + pg_temp.h('vt:' || d.dir_no || ':' || k.slot, 3)]
END;

INSERT INTO vehicles (operator_id, license_plate, vehicle_type, seat_capacity, status)
SELECT (SELECT id FROM bus_operators b WHERE lower(b.name) = lower(v.operator_name)),
       v.plate, v.type_name, v.capacity, 'ACTIVE'
FROM seed_vehicles v
ON CONFLICT DO NOTHING;

-- ---------- Trips: 3–6 departures per direction per day ----------
CREATE TEMP TABLE seed_trips ON COMMIT DROP AS
WITH day_plan AS (
    SELECT d.dir_no, d.minutes, g.day_offset,
           3 + pg_temp.h('n:' || d.dir_no || ':' || g.day_offset, 4) AS departures
    FROM seed_dirs d
    CROSS JOIN generate_series(-14, 60) AS g(day_offset)
), slots AS (
    SELECT p.*, s.slot,
           pg_temp.utc((pg_temp.vn_today() + p.day_offset) + interval '5 hours'
               + make_interval(mins => s.slot * (1110 / p.departures / 15 * 15)
                   + 15 * pg_temp.h('j:' || p.dir_no || ':' || p.day_offset || ':' || s.slot, 5))) AS departure_time
    FROM day_plan p
    CROSS JOIN LATERAL generate_series(0, p.departures - 1) AS s(slot)
)
SELECT s.dir_no, s.day_offset, s.slot, s.departure_time,
       s.departure_time + make_interval(mins => s.minutes
           + 10 * (pg_temp.h('a:' || s.dir_no || ':' || s.day_offset || ':' || s.slot, 5) - 1)) AS arrival_time,
       r.id AS route_id, veh.id AS vehicle_id, v.capacity,
       greatest(90000, round(s.minutes * 1100 * v.price_factor / 10000) * 10000) AS price,
       pg_temp.h('s:' || s.dir_no || ':' || s.day_offset || ':' || s.slot, 100) AS fill_roll,
       pg_temp.h('c:' || s.dir_no || ':' || s.day_offset || ':' || s.slot, 33) = 0 AS cancelled
FROM slots s
JOIN seed_dirs d ON d.dir_no = s.dir_no
JOIN routes r ON r.origin_id = d.origin_id AND r.destination_id = d.dest_id
JOIN seed_vehicles v ON v.dir_no = s.dir_no AND v.slot = s.slot AND v.parity = mod(s.day_offset + 1000, 2)
JOIN vehicles veh ON veh.license_plate = v.plate;

INSERT INTO trips (route_id, vehicle_id, departure_time, arrival_time, price, available_seats, status)
SELECT t.route_id, t.vehicle_id, t.departure_time, t.arrival_time, t.price,
       -- About 8% sold out, 14% down to their last five seats, the rest partly sold.
       CASE WHEN t.fill_roll < 8 THEN 0
            WHEN t.fill_roll < 22 THEN least(t.capacity, 1 + t.fill_roll % 5)
            ELSE greatest(least(t.capacity, 6), t.capacity - pg_temp.h('q:' || t.dir_no || ':' || t.day_offset || ':' || t.slot, t.capacity))
       END,
       CASE WHEN t.cancelled THEN 'CANCELLED'
            WHEN t.arrival_time <= pg_temp.utc_now() THEN 'COMPLETED'
            WHEN t.departure_time <= pg_temp.utc_now() THEN 'IN_PROGRESS'
            ELSE 'SCHEDULED'
       END
FROM seed_trips t
-- Skip a trip already seeded, or one that would clash with the coach's existing schedule
-- (a rerun after editing this file must not trip trips_vehicle_schedule_no_overlap).
WHERE NOT EXISTS (
    SELECT 1 FROM trips x
    WHERE x.vehicle_id = t.vehicle_id
      AND (x.departure_time = t.departure_time
           OR (x.status <> 'CANCELLED'
               AND tsrange(x.departure_time, x.arrival_time) && tsrange(t.departure_time, t.arrival_time)))
);
