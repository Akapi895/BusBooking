"""Bulk fixture setup is outside measured windows; assertions use real HTTP/transactions."""
import datetime as dt
import secrets

import bcrypt

from .common import save


class Fixtures:
    def __init__(self, runtime):
        self.rt = runtime
        self.password = "AcceptanceA1!" + secrets.token_urlsafe(12)
        self.data = {}

    def prepare(self, *, snapshot=True):
        f = self.rt.config["fixture"]
        password_hash = bcrypt.hashpw(self.password.encode(), bcrypt.gensalt(rounds=10)).decode()
        with self.rt.connect() as conn:
            roles = dict(conn.execute("SELECT name,id FROM roles").fetchall())
            principals = {}
            for role in ("SUPER_ADMIN", "ADMIN", "USER"):
                email = role.lower() + "@acceptance.example"
                uid = conn.execute("INSERT INTO users(full_name,email,password,phone,role_id,status,email_verified) "
                    "VALUES(%s,%s,%s,'0901234567',%s,'ACTIVE',true) RETURNING id",
                    ("Acceptance " + role, email, password_hash, roles[role])).fetchone()[0]
                principals[role] = {"id": uid, "email": email}
            users = [r[0] for r in conn.execute("INSERT INTO users(full_name,email,password,phone,role_id,status,email_verified) "
                "SELECT 'Load User '||g,'load-'||g||'@acceptance.example',%s,'0901234567',%s,'ACTIVE',true "
                "FROM generate_series(1,%s) g RETURNING id", (password_hash, roles["USER"], f["users"])).fetchall()]
            locations = [r[0] for r in conn.execute("INSERT INTO locations(name,province,address) "
                "SELECT 'Load Station '||g,'Test Province','Address '||g FROM generate_series(1,101) g RETURNING id").fetchall()]
            operator = conn.execute("INSERT INTO bus_operators(name,address,phone,email,status) "
                "VALUES('Load Operator','Test Address','0901234567','operator@acceptance.example','ACTIVE') RETURNING id").fetchone()[0]
            routes, vehicles = [], []
            for i in range(100):
                routes.append(conn.execute("INSERT INTO routes(origin_id,destination_id,estimated_duration_minutes,status) "
                    "VALUES(%s,%s,120,'ACTIVE') RETURNING id", (locations[i], locations[i + 1])).fetchone()[0])
                vehicles.append(conn.execute("INSERT INTO vehicles(operator_id,license_plate,vehicle_type,seat_capacity,status) "
                    "VALUES(%s,%s,'BUS',%s,'ACTIVE') RETURNING id", (operator, f"LT-{i:05d}", f["capacity"])).fetchone()[0])
            trips = conn.execute("INSERT INTO trips(route_id,vehicle_id,departure_time,arrival_time,price,available_seats,status) "
                "SELECT (%s::bigint[])[1+(g-1)%%100],(%s::bigint[])[1+(g-1)%%100],"
                "date_trunc('day',now())+interval '30 days'+((g-1)/100)*interval '4 hours',"
                "date_trunc('day',now())+interval '30 days'+((g-1)/100)*interval '4 hours'+interval '2 hours',"
                "150000,%s,'SCHEDULED' FROM generate_series(1,%s) g RETURNING id,route_id,departure_time",
                (routes, vehicles, f["capacity"], f["trips"])).fetchall()
            self.data = {"principals": principals, "users": users, "locations": locations, "operator": operator,
                         "routes": routes, "vehicles": vehicles, "capacity": f["capacity"],
                         "trips": [{"id": tid, "route": route, "origin": locations[routes.index(route)],
                                    "destination": locations[routes.index(route) + 1], "date": str(date.date())}
                                   for tid, route, date in trips],
                         "price": 150000, "setup": "SQL fixture, no claim that bulk users exercised registration"}
        save(self.rt.root / "fixture.json", self.data)
        if snapshot:
            self.rt.snapshot()
        return self.data

    def new_user(self, role="USER", verified=True):
        email = secrets.token_hex(10) + "@acceptance.example"
        with self.rt.connect() as conn:
            uid = conn.execute("INSERT INTO users(full_name,email,password,phone,role_id,status,email_verified) "
                "SELECT 'Race User',%s,password,'0901234567',(SELECT id FROM roles WHERE name=%s),'ACTIVE',%s "
                "FROM users WHERE id=%s RETURNING id", (email, role, verified, self.data["users"][0])).fetchone()[0]
        return {"id": uid, "email": email}

    def new_vehicle(self, capacity=40):
        with self.rt.connect() as conn:
            return conn.execute("INSERT INTO vehicles(operator_id,license_plate,vehicle_type,seat_capacity,status) "
                "VALUES(%s,%s,'BUS',%s,'ACTIVE') RETURNING id",
                (self.data["operator"], "R-" + secrets.token_hex(7).upper(), capacity)).fetchone()[0]

    def new_trip(self, capacity=40):
        vehicle = self.new_vehicle(capacity)
        with self.rt.connect() as conn:
            trip = conn.execute("INSERT INTO trips(route_id,vehicle_id,departure_time,arrival_time,price,available_seats,status) "
                "VALUES(%s,%s,now()+interval '60 days',now()+interval '60 days 2 hours',150000,%s,'SCHEDULED') RETURNING id",
                (self.data["routes"][0], vehicle, capacity)).fetchone()[0]
        return trip, vehicle

    def trip_body(self, vehicle):
        start = dt.datetime.now(dt.timezone(dt.timedelta(hours=7))).replace(tzinfo=None, microsecond=0) + dt.timedelta(days=100)
        return {"routeId": self.data["routes"][0], "vehicleId": vehicle,
                "departureTime": start.isoformat(), "arrivalTime": (start + dt.timedelta(hours=2)).isoformat(), "price": 150000}

    def verify(self, marker=None, acknowledged=None):
        with self.rt.connect() as conn:
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            conn.execute("SET LOCAL statement_timeout='30000ms'")
            # Aggregate once, outside the measured window. Include cancelled and untouched trips.
            inconsistent = conn.execute("WITH seats AS (SELECT trip_id,sum(quantity) qty FROM bookings "
                "WHERE status IN ('HELD','CONFIRMED') GROUP BY trip_id) SELECT count(*) FROM trips t "
                "JOIN vehicles v ON v.id=t.vehicle_id LEFT JOIN seats s ON s.trip_id=t.id "
                "WHERE t.available_seats<0 OR t.available_seats>v.seat_capacity "
                "OR t.available_seats+coalesce(s.qty,0)<>v.seat_capacity").fetchone()[0]
            bad_money = conn.execute("SELECT count(*) FROM bookings WHERE total_amount<>unit_price*quantity").fetchone()[0]
            # A cancelled trip cancels its holds and refunds its confirmed bookings in the same transaction.
            inconsistent += conn.execute("SELECT count(*) FROM bookings b JOIN trips t ON t.id=b.trip_id "
                "WHERE t.status='CANCELLED' AND b.status IN ('HELD','CONFIRMED')").fetchone()[0]
            committed = conn.execute("SELECT count(*) FROM bookings WHERE passenger_name LIKE %s", (marker + "%",)).fetchone()[0] if marker else None
            counts = {name: conn.execute("SELECT count(*) FROM " + name).fetchone()[0]
                      for name in ("users", "trips", "bookings")}
        return {"seat_violations": inconsistent, "money_violations": bad_money, "counts": counts,
                "committed": committed, "acknowledged": acknowledged,
                "unacknowledged_commits": committed - acknowledged if committed is not None and acknowledged is not None else None,
                "status": "FAIL" if inconsistent or bad_money or
                (committed is not None and acknowledged is not None and committed < acknowledged) else "PASS"}
