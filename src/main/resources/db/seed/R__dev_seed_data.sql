-- Demo accounts and their bookings, for local development only.
-- Loaded only by the dev profile (spring.flyway.locations in application-dev.properties);
-- the test profile and production never run it. Needs the demo catalogue (db/catalogue), which
-- Flyway runs first ("demo catalogue" sorts before "dev seed data").
-- Repeatable: Flyway re-runs it whenever this file changes, and every insert skips rows that exist.
--
-- Accounts, all with password matkhau123 and a verified email:
--   demo@busbooking.local   USER, about 70 bookings in every status
--   admin@busbooking.local  ADMIN
--   khach001..khach150@busbooking.local  USER, booking history spread over the catalogue

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

-- ---------- Users (password: matkhau123) ----------
INSERT INTO users (full_name, email, password, phone, role_id, status, email_verified)
VALUES
    ('Nguyễn Minh Anh', 'demo@busbooking.local', '$2b$10$O5k6uCPCvyzwWnY3VJS0f.bdg8EQvTx4XkuA/ohLTN1WgLw3bulOG',
     '0912345678', (SELECT id FROM roles WHERE name = 'USER'), 'ACTIVE', TRUE),
    ('Quản trị viên', 'admin@busbooking.local', '$2b$10$O5k6uCPCvyzwWnY3VJS0f.bdg8EQvTx4XkuA/ohLTN1WgLw3bulOG',
     '0987000111', (SELECT id FROM roles WHERE name = 'ADMIN'), 'ACTIVE', TRUE)
ON CONFLICT (email) DO NOTHING;

INSERT INTO users (full_name, email, password, phone, role_id, status, email_verified)
SELECT (ARRAY['Nguyễn', 'Trần', 'Lê', 'Phạm', 'Hoàng', 'Huỳnh', 'Phan', 'Vũ', 'Võ', 'Đặng', 'Bùi', 'Đỗ', 'Hồ', 'Ngô', 'Dương', 'Lý'])[1 + pg_temp.h('ho:' || n, 16)]
           || ' ' || (ARRAY['Văn', 'Thị', 'Minh', 'Ngọc', 'Thanh', 'Quốc', 'Gia', 'Thu', 'Hoài', 'Đức', 'Bảo', 'Anh'])[1 + pg_temp.h('dem:' || n, 12)]
           || ' ' || (ARRAY['An', 'Bình', 'Châu', 'Dũng', 'Giang', 'Hà', 'Hải', 'Hùng', 'Khánh', 'Lan', 'Linh', 'Long', 'Mai', 'Nam',
                            'Nhung', 'Phong', 'Phúc', 'Quân', 'Quỳnh', 'Sơn', 'Tâm', 'Thảo', 'Trang', 'Trung', 'Tuấn', 'Vy', 'Yến'])[1 + pg_temp.h('ten:' || n, 27)],
       'khach' || lpad(n::text, 3, '0') || '@busbooking.local',
       '$2b$10$O5k6uCPCvyzwWnY3VJS0f.bdg8EQvTx4XkuA/ohLTN1WgLw3bulOG',
       '09' || lpad((10000000 + n * 379721 % 89999999)::text, 8, '0'),
       (SELECT id FROM roles WHERE name = 'USER'), 'ACTIVE', TRUE
FROM generate_series(1, 150) AS n
ON CONFLICT (email) DO NOTHING;

-- ---------- Bookings ----------
-- The demo account books ~1 in 140 seeded trips from two weeks ago to a month ahead (~70);
-- each other customer books ~1 in 900 across the whole window (~15 each).
CREATE TEMP TABLE seed_bookings ON COMMIT DROP AS
SELECT u.id AS user_id, u.email, u.full_name, u.phone, t.id AS trip_id, t.status AS trip_status,
       t.price, t.departure_time, v.seat_capacity,
       u.email || ':' || t.id AS k
FROM users u
JOIN trips t ON t.status <> 'IN_PROGRESS'
JOIN vehicles v ON v.id = t.vehicle_id
-- Only coaches from the demo catalogue: plates <province>B90001 .. <province>B90480.
-- (The catalogue's temp tables are gone by now; it runs as a separate migration.)
WHERE v.license_plate ~ '^[0-9]{2}B9[0-9]{4}$' AND right(v.license_plate, 5)::int BETWEEN 90001 AND 90480
  AND ((u.email = 'demo@busbooking.local'
        AND t.departure_time < pg_temp.utc(pg_temp.vn_today() + 30)
        AND pg_temp.h('pick:' || u.email || ':' || t.id, 140) = 0)
   OR (u.email LIKE 'khach___@busbooking.local'
        AND pg_temp.h('pick:' || u.email || ':' || t.id, 900) = 0));

INSERT INTO bookings (booking_code, user_id, trip_id, passenger_name, passenger_phone, quantity,
                      unit_price, total_amount, status, booked_at, refunded_at)
SELECT 'BK' || upper(substr(md5(b.k), 1, 8)),
       b.user_id, b.trip_id,
       CASE WHEN pg_temp.h('pn:' || b.k, 4) = 0 THEN 'Trần Thu Hà' ELSE b.full_name END,
       b.phone,
       q.quantity, b.price, b.price * q.quantity,
       CASE WHEN b.trip_status = 'CANCELLED'
                THEN (ARRAY['REFUND_PENDING', 'REFUNDED'])[1 + pg_temp.h('rf:' || b.k, 2)]
            WHEN pg_temp.h('cx:' || b.k, 100) < 12 THEN 'CANCELLED'
            ELSE 'CONFIRMED'
       END,
       least(pg_temp.utc_now() - make_interval(mins => 5 + pg_temp.h('bt:' || b.k, 600)),
             b.departure_time - make_interval(days => 1 + pg_temp.h('bd:' || b.k, 10))),
       CASE WHEN b.trip_status = 'CANCELLED' AND pg_temp.h('rf:' || b.k, 2) = 1 THEN now() - interval '1 day' END
FROM seed_bookings b
CROSS JOIN LATERAL (SELECT least(b.seat_capacity, 1 + pg_temp.h('qty:' || b.k, 3)) AS quantity) q
ON CONFLICT (booking_code) DO NOTHING;
