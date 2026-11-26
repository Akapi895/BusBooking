"""Black-box contracts and concurrent schedules against the application."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
import re
import secrets
import struct
import threading
import time
import zipfile

import requests

from .common import append, jwt, save
from .contracts import ENDPOINTS, booking_valid, canonical, reset_code, verification_code


class Acceptance:
    def __init__(self, rt, fixtures):
        self.rt, self.fx = rt, fixtures
        self.results, self.covered = [], set()
        self.http_log = rt.root / "acceptance-http.jsonl"
        self._lock = threading.Lock()

    def token(self, who="USER"):
        uid = self.fx.data["principals"][who]["id"] if isinstance(who, str) else who
        return jwt(uid, self.rt.secret)

    def request(self, method, path, who="USER", body=None, expected=None, timeout=45, raw_token=None, key=None):
        start = time.time()
        headers = {"Authorization": "Bearer " + self.token(who)} if who is not None else {}
        if raw_token is not None:
            headers = {"Authorization": "Bearer " + raw_token}
        if key is not None:
            headers["Idempotency-Key"] = key
        response = requests.request(method, self.rt.url + path, json=body, headers=headers, timeout=(5, timeout))
        try:
            result = response.json() if response.content else None
        except ValueError:
            result = None
        event = {"method": method, "endpoint": canonical(path), "status": response.status_code,
                 "start": start, "end": time.time(), "error": result.get("error") if isinstance(result, dict) else None}
        with self._lock:
            append(self.http_log, event)
            if 200 <= response.status_code < 300:
                self.covered.add((method, canonical(path)))
        if expected is not None:
            allowed = (expected,) if isinstance(expected, int) else expected
            if response.status_code not in allowed:
                raise AssertionError(f"{method} {canonical(path)}: expected {allowed}, got {response.status_code}/{event['error']}")
        if response.status_code >= 400:
            assert isinstance(result, dict) and {"status", "error", "message", "path"} <= result.keys(), "Error envelope missing"
            assert result["status"] == response.status_code, "Error status mismatch"
        if result and isinstance(result, dict) and result.get("error") == "SERVICE_UNAVAILABLE":
            assert response.headers.get("Retry-After") == "1", "Missing retry delay"
        return response.status_code, result

    def case(self, name, action):
        start = time.time()
        try:
            self.rt.restore()
            evidence = action()
            oracle = self.fx.verify()
            assert oracle["status"] == "PASS", oracle
            result = {"name": name, "status": "PASS", "evidence": evidence, "oracle": oracle}
        except Exception as error:
            result = {"name": name, "status": "FAIL", "error": type(error).__name__,
                      "detail": str(error)[:250] if isinstance(error, AssertionError) else "See metadata; payloads omitted"}
        result["seconds"] = time.time() - start
        self.results.append(result)
        save(self.rt.root / "acceptance.json", self.results)
        print(name, result["status"], flush=True)
        return result

    def book(self, trip, who="USER", quantity=1, expected=None, timeout=45, key=None):
        return self.request("POST", "/api/bookings", who,
            {"tripId": trip, "passengerName": "Acceptance", "passengerPhone": "0901234567", "quantity": quantity},
            expected, timeout, key=key)

    def counts(self, trip):
        with self.rt.connect() as conn:
            return conn.execute("SELECT t.available_seats,count(b.id),coalesce(sum(b.quantity) FILTER "
                "(WHERE b.status IN ('HELD','CONFIRMED')),0),t.status FROM trips t LEFT JOIN bookings b ON b.trip_id=t.id "
                "WHERE t.id=%s GROUP BY t.id", (trip,)).fetchone()

    def burst(self, actions):
        barrier = threading.Barrier(len(actions))
        starts = []
        def run(action):
            barrier.wait(timeout=30)
            starts.append(time.monotonic())
            return action()
        with ThreadPoolExecutor(max_workers=len(actions)) as pool:
            futures = [pool.submit(run, action) for action in actions]
            values = [future.result(timeout=60) for future in futures]
        return values, (max(starts) - min(starts)) * 1000

    def otp(self, email, timeout=20, find=verification_code):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                inbox = requests.get("http://127.0.0.1:8025/api/v1/messages", timeout=3)
                inbox.raise_for_status()
                for message in inbox.json()["messages"]:
                    if any(address.get("Address") == email for address in message.get("To", [])):
                        response = requests.get("http://127.0.0.1:8025/api/v1/message/" + message["ID"], timeout=3)
                        response.raise_for_status()
                        code = find(response.json().get("Text", ""))
                        if code:
                            return code
            except requests.RequestException:
                pass
            time.sleep(0.2)
        raise AssertionError("OTP not delivered for test recipient")

    def registration(self, email, expected=201):
        return self.request("POST", "/api/auth/register", None,
            {"fullName": "Acceptance User", "email": email, "password": self.fx.password, "phone": "0901234567"}, expected)

    def auth(self):
        email = secrets.token_hex(8) + "@acceptance.example"
        self.registration(email)
        self.request("POST", "/api/auth/login", None, {"email": email, "password": self.fx.password}, 401)
        self.registration(email, 409)
        code = self.otp(email)
        self.request("POST", "/api/auth/verify-email", None, {"email": email, "code": code}, 204)
        self.request("POST", "/api/auth/verify-email", None, {"email": email, "code": code}, 400)
        _, login = self.request("POST", "/api/auth/login", None, {"email": email, "password": self.fx.password}, 200)
        me = requests.get(self.rt.url + "/api/auth/me", headers={"Authorization": "Bearer " + login["token"]}, timeout=10)
        assert me.status_code == 200 and me.json()["email"] == email
        self.request("POST", "/api/auth/resend-verification", None, {"email": email}, 202)

        # Changing or resetting the password and logging out each revoke every earlier token.
        changed = "Changed" + self.fx.password
        password = {"currentPassword": self.fx.password + "x", "newPassword": changed}
        self.request("PUT", "/api/users/me/password", None, password, 400, raw_token=login["token"])
        password["currentPassword"] = self.fx.password
        self.request("PUT", "/api/users/me/password", None, password, 204, raw_token=login["token"])
        self.request("GET", "/api/auth/me", None, expected=401, raw_token=login["token"])
        self.request("POST", "/api/auth/login", None, {"email": email, "password": self.fx.password}, 401)
        _, login = self.request("POST", "/api/auth/login", None, {"email": email, "password": changed}, 200)
        self.request("POST", "/api/auth/logout", None, expected=204, raw_token=login["token"])
        self.request("GET", "/api/auth/me", None, expected=401, raw_token=login["token"])
        self.request("POST", "/api/auth/forgot-password", None, {"email": email}, 202)
        code = self.otp(email, find=reset_code)
        reset = "Reset" + self.fx.password
        self.request("POST", "/api/auth/reset-password", None, {"email": email, "code": code, "newPassword": reset}, 204)
        self.request("POST", "/api/auth/reset-password", None, {"email": email, "code": code, "newPassword": changed}, 400)
        self.request("POST", "/api/auth/login", None, {"email": email, "password": reset}, 200)
        return {"registration_otp_login": True, "one_time_code": True,
                "password_change_logout_reset_revoke_tokens": True}

    def catalog(self):
        suffix = secrets.token_hex(4)
        resources = {}
        bodies = {
            "locations": {"name": "  Test   " + suffix, "province": "Test", "address": "Address"},
            "operators": {"name": "Test " + suffix, "address": "Address", "phone": "0901234567", "email": suffix + "@example.com"},
        }
        for resource in ("locations", "operators", "vehicles", "routes"):
            if resource == "vehicles":
                bodies[resource] = {"operatorId": resources["operators"], "licensePlate": "A-" + suffix, "vehicleType": "BUS", "seatCapacity": 40}
            if resource == "routes":
                _, dest = self.request("POST", "/api/admin/locations", "ADMIN",
                    {"name": "Destination " + suffix, "province": "Test", "address": "Address"}, 201)
                bodies[resource] = {"originId": resources["locations"], "destinationId": dest["id"], "estimatedDurationMinutes": 120}
            path = "/api/admin/" + resource
            _, created = self.request("POST", path, "ADMIN", bodies[resource], 201)
            resources[resource] = created["id"]
            update = dict(bodies[resource])
            if resource != "locations":
                update["status"] = "ACTIVE"
            self.request("PUT", path + "/" + str(created["id"]), "ADMIN", update, 200)
            _, listed = self.request("GET", path, "ADMIN", expected=200)
            assert any(item["id"] == created["id"] for item in listed)
            self.request("POST", path, "ADMIN", bodies[resource], 409)
        body = self.fx.trip_body(resources["vehicles"])
        body["routeId"] = resources["routes"]
        _, trip = self.request("POST", "/api/admin/trips", "ADMIN", body, 201)
        body["price"] = 175000
        self.request("PUT", f"/api/admin/trips/{trip['id']}", "ADMIN", body, 200)
        self.request("GET", "/api/admin/trips?status=SCHEDULED", "ADMIN", expected=200)
        self.request("GET", f"/api/trips/{trip['id']}", None, expected=200)
        _, booking = self.book(trip["id"], quantity=2, expected=201)
        assert booking_valid(booking, 0, trip["id"], 2, 175000) and booking["status"] == "HELD"
        _, confirmed = self.request("POST", f"/api/bookings/{booking['id']}/confirm", expected=200)
        assert confirmed["status"] == "CONFIRMED"
        self.request("GET", f"/api/bookings/{booking['id']}", expected=200)
        self.request("GET", f"/api/bookings/{booking['id']}", self.fx.data["users"][0], expected=403)
        _, history = self.request("GET", "/api/users/me/bookings", expected=200)
        assert any(b["id"] == booking["id"] for b in history)
        self.request("GET", "/api/admin/bookings?tripId=" + str(trip["id"]), "ADMIN", expected=200)
        self.request("DELETE", f"/api/bookings/{booking['id']}", expected=200)
        _, again = self.request("DELETE", f"/api/bookings/{booking['id']}", expected=200)
        assert again["status"] == "CANCELLED" and self.counts(trip["id"])[0] == 40
        # Cancelling a trip with a confirmed booking queues a refund and a notice email.
        _, booked = self.book(trip["id"], quantity=1, expected=201)
        self.request("POST", f"/api/bookings/{booked['id']}/confirm", expected=200)
        self.request("DELETE", f"/api/admin/trips/{trip['id']}", "ADMIN", expected=200)
        self.request("DELETE", f"/api/admin/trips/{trip['id']}", "ADMIN", expected=200)
        assert self.counts(trip["id"])[0] == 40
        self.request("DELETE", f"/api/bookings/{booked['id']}", expected=400)
        _, pending = self.request("GET", f"/api/admin/bookings?status=REFUND_PENDING&tripId={trip['id']}", "ADMIN", expected=200)
        assert [b["id"] for b in pending] == [booked["id"]], pending
        self.otp(self.fx.data["principals"]["USER"]["email"],
                 find=lambda text: booked["bookingCode"] if booked["bookingCode"] in text else None)
        refund = f"/api/admin/bookings/{booked['id']}/refund"
        self.request("POST", refund, "USER", expected=403)
        _, refunded = self.request("POST", refund, "ADMIN", expected=200)
        assert refunded["status"] == "REFUNDED"
        self.request("POST", refund, "ADMIN", expected=400)
        return {"crud": resources, "lifecycle": True, "trip_cancel_refund": True}

    def security(self):
        self.request("GET", "/api/auth/me", expected=200)
        uid_for_token = self.fx.data["users"][0]
        for token in ("malformed.jwt", jwt(uid_for_token, self.rt.secret, ttl=1, now=int(time.time()) - 60),
                      jwt(uid_for_token, self.rt.secret, now=int(time.time()) + 60),
                      jwt(uid_for_token, self.rt.secret, issuer="wrong-issuer")):
            self.request("GET", "/api/auth/me", expected=401, raw_token=token)
        self.request("GET", "/api/users/me", expected=200)
        self.request("PUT", "/api/users/me", body={"fullName": "Updated User", "phone": "0901234567"}, expected=200)
        self.request("PUT", "/api/users/me", body={"fullName": "Changed", "phone": "0901234567", "role": "ADMIN"}, expected=400)
        self.request("GET", "/api/locations?q=Load", None, expected=200)
        t = self.fx.data["trips"][0]
        _, found = self.request("GET", f"/api/trips?originId={t['origin']}&destinationId={t['destination']}&departureDate={t['date']}", None, expected=200)
        assert found and all(x["routeId"] == self.fx.data["routes"][0] and x["departureTime"][:10] == t["date"] for x in found)
        _, empty = self.request("GET", "/api/trips?originId=9223372036854775807", None, expected=200)
        assert empty == []
        for query in ("originId=bad", "departureDate=2026-02-30"):
            self.request("GET", "/api/trips?" + query, None, expected=400)
        self.book(t["id"], quantity=0, expected=400)
        self.book(t["id"], who="ADMIN", expected=403)
        self.book(t["id"], who="SUPER_ADMIN", expected=403)
        self.request("GET", "/api/users/me/bookings", "ADMIN", expected=403)
        for method, path in sorted(ENDPOINTS):
            if path.startswith("/api/admin/"):
                path = path.replace("{id}", "1")
                self.request(method, path, None, {} if method != "GET" else None, 401)
                self.request(method, path, "USER", {} if method != "GET" else None, 403)
        uid = self.fx.data["users"][1]
        unchanged_token = self.token(uid)
        for role, expected in (("ADMIN", 200), ("USER", 403)):
            self.request("PUT", f"/api/admin/users/{uid}/role", "SUPER_ADMIN", {"role": role}, 200)
            self.request("GET", "/api/admin/locations", uid, expected=expected, raw_token=unchanged_token)
        self.request("PUT", f"/api/admin/users/{uid}/role", "ADMIN", {"role": "ADMIN"}, 403)
        self.request("PUT", f"/api/admin/users/{uid}/role", "SUPER_ADMIN", {"role": "SUPER_ADMIN"}, 400)
        with self.rt.connect() as conn:
            conn.execute("UPDATE users SET status='INACTIVE' WHERE id=%s", (uid,))
        self.request("GET", "/api/auth/me", uid, expected=401, raw_token=unchanged_token)
        return {"database_role_reload": True, "ownership_and_roles": True}

    def rate_limit(self):
        self.rt.restart_app()  # Clear only the owned instance's in-memory counters, not change limits.
        counts = Counter()
        for _ in range(11):
            status, _ = self.request("POST", "/api/auth/login", None,
                {"email": "unknown@acceptance.example", "password": self.fx.password}, (401, 429))
            counts[status] += 1
        assert counts == {401: 10, 429: 1}, "Default per-IP login rate limiter differs"
        return dict(counts)

    def concurrency(self):
        cfg = self.rt.config["concurrency"]
        evidence = []
        for i in range(cfg["rounds"]):
            n = cfg["bursts"][i % len(cfg["bursts"])]
            seats = cfg["last_seats"][i % len(cfg["last_seats"]) ]
            quantity = 2 if i % 4 == 3 else 1
            winners = min(seats // quantity, n)
            trip, _ = self.fx.new_trip(seats)
            values, spread = self.burst([lambda uid=uid: self.book(trip, uid, quantity)
                                         for uid in self.fx.data["users"][:n]])
            codes = Counter(v[0] for v in values)
            assert set(codes) <= {201, 409, 503} and sum(codes.values()) == n, dict(codes)
            assert codes[201] == min(seats // quantity, n - codes[503]), dict(codes)
            assert codes[201] <= winners
            assert all(body.get("error") == "INSUFFICIENT_SEATS" for code, body in values if code == 409)
            assert all(body.get("error") == "SERVICE_UNAVAILABLE" for code, body in values if code == 503)
            left, bookings, confirmed, _ = self.counts(trip)
            assert left == seats - codes[201] * quantity and bookings == codes[201] and confirmed == codes[201] * quantity
            evidence.append({"round": i, "burst": n, "capacity": seats, "quantity": quantity,
                             "codes": dict(codes), "dispatch_spread_ms": spread})
        return evidence

    def cancel_races(self):
        evidence = []
        for _ in range(max(3, self.rt.config["concurrency"]["rounds"] // 5)):
            trip, _ = self.fx.new_trip(2)
            _, booking = self.book(trip, expected=201)
            values, spread = self.burst([lambda: self.request("DELETE", f"/api/bookings/{booking['id']}") for _ in range(10)])
            # Repeated cancels are idempotent (200); the seat must still come back only once.
            assert Counter(v[0] for v in values) == {200: 10}
            assert self.counts(trip)[:3] == (2, 1, 0)
            _, old = self.book(trip, quantity=2, expected=201)
            values, _ = self.burst([lambda: self.book(trip, self.fx.data["users"][0]),
                                    lambda: self.request("DELETE", f"/api/bookings/{old['id']}")])
            assert values[0][0] in (201, 409) and values[1][0] == 200
            assert self.counts(trip)[0] == (1 if values[0][0] == 201 else 2)
            evidence.append({"double_cancel_dispatch_ms": spread, "create_cancel": [v[0] for v in values]})
        return evidence

    def admin_races(self):
        evidence = []
        for _ in range(max(3, self.rt.config["concurrency"]["rounds"] // 5)):
            trip, _ = self.fx.new_trip(2)
            values, spread = self.burst([lambda: self.book(trip),
                lambda: self.request("DELETE", f"/api/admin/trips/{trip}", "ADMIN")])
            codes = tuple(v[0] for v in values)
            # The cancel always wins; a booking that got in first is moved to REFUND_PENDING.
            assert codes in ((201, 200), (400, 200)), codes
            left, count, confirmed, status = self.counts(trip)
            assert status == "CANCELLED" and left == 2 and confirmed == 0 and count == (codes[0] == 201), (left, count, confirmed, status)
            trip, _ = self.fx.new_trip(2)
            small = self.fx.new_vehicle(1)
            _, current = self.request("GET", f"/api/trips/{trip}", None, expected=200)
            body = self.fx.trip_body(small)
            body.update(departureTime=current["departureTime"], arrivalTime=current["arrivalTime"])
            values, _ = self.burst([lambda: self.book(trip, quantity=2),
                lambda: self.request("PUT", f"/api/admin/trips/{trip}", "ADMIN", body)])
            assert tuple(v[0] for v in values) in ((201, 409), (409, 200)), [v[0] for v in values]
            evidence.append({"booking_trip_cancel": codes, "dispatch_spread_ms": spread,
                             "booking_vehicle_change": [v[0] for v in values]})
        return evidence

    def unique_races(self):
        suffix = secrets.token_hex(5)
        bodies = {
            "locations": {"name": "Race " + suffix, "province": "Test", "address": "Address"},
            "operators": {"name": "Race " + suffix, "address": "Address", "phone": "0901234567", "email": suffix + "@example.com"},
            "vehicles": {"operatorId": self.fx.data["operator"], "licensePlate": "U-" + suffix, "vehicleType": "BUS", "seatCapacity": 40},
        }
        with self.rt.connect() as conn:
            route = conn.execute("INSERT INTO locations(name,province,address) VALUES(%s,'Test','Address') RETURNING id", (suffix,)).fetchone()[0]
        bodies["routes"] = {"originId": self.fx.data["locations"][0], "destinationId": route, "estimatedDurationMinutes": 120}
        result = {}
        for resource, body in bodies.items():
            values, spread = self.burst([lambda: self.request("POST", "/api/admin/" + resource, "ADMIN", body) for _ in range(2)])
            assert sorted(v[0] for v in values) == [201, 409], resource
            result[resource] = {"codes": [v[0] for v in values], "dispatch_spread_ms": spread}
        return result

    def assignment_races(self):
        result = []
        for resource in ("vehicles", "routes"):
            suffix = secrets.token_hex(5)
            if resource == "vehicles":
                body = {"operatorId": self.fx.data["operator"], "licensePlate": "D-" + suffix,
                        "vehicleType": "BUS", "seatCapacity": 40}
            else:
                _, destination = self.request("POST", "/api/admin/locations", "ADMIN",
                    {"name": "Race Destination " + suffix, "province": "Test", "address": "Address"}, 201)
                body = {"originId": self.fx.data["locations"][0], "destinationId": destination["id"], "estimatedDurationMinutes": 120}
            _, item = self.request("POST", "/api/admin/" + resource, "ADMIN", body, 201)
            update = dict(body, status="INACTIVE")
            trip = self.fx.trip_body(item["id"] if resource == "vehicles" else self.fx.new_vehicle())
            if resource == "routes":
                trip["routeId"] = item["id"]
            values, spread = self.burst([
                lambda: self.request("POST", "/api/admin/trips", "ADMIN", trip),
                lambda: self.request("PUT", f"/api/admin/{resource}/{item['id']}", "ADMIN", update)])
            assert tuple(v[0] for v in values) in ((201, 409), (400, 200)), (resource, [v[0] for v in values])
            result.append({"resource": resource, "codes": [v[0] for v in values], "dispatch_spread_ms": spread})
        return result

    def profile_race(self):
        uid = self.fx.data["users"][0]
        bodies = [{"fullName": "Writer One", "phone": "0901234567"},
                  {"fullName": "Writer Two", "phone": "0912345678"}]
        values, spread = self.burst([lambda body=body: self.request("PUT", "/api/users/me", uid, body) for body in bodies])
        assert all(value[0] == 200 for value in values)
        _, final = self.request("GET", "/api/users/me", uid, expected=200)
        assert {"fullName": final["fullName"], "phone": final["phone"]} in bodies
        return {"atomic_pair": True, "policy": "last writer wins; no optimistic version in current API", "dispatch_spread_ms": spread}

    def otp_races(self):
        self.rt.restart_app()
        email = secrets.token_hex(7) + "@acceptance.example"
        values, _ = self.burst([lambda: self.registration(email, (201, 409)) for _ in range(2)])
        assert sorted(v[0] for v in values) == [201, 409]
        code = self.otp(email)
        values, _ = self.burst([lambda: self.request("POST", "/api/auth/verify-email", None,
            {"email": email, "code": code}) for _ in range(2)])
        assert sorted(v[0] for v in values) == [204, 400]
        pending = self.fx.new_user(verified=False)
        # Construct an expired/cooldown-eligible challenge; do not alter app clock or TTL.
        with self.rt.connect() as conn:
            conn.execute("INSERT INTO email_verifications(user_id,code_hash,sent_at,expires_at,failed_attempts) "
                         "VALUES(%s,%s,now()-interval '11 minutes',now()-interval '1 minute',0)", (pending["id"], "0" * 64))
        values, _ = self.burst([lambda: self.request("POST", "/api/auth/resend-verification", None,
            {"email": pending["email"]}) for _ in range(2)])
        assert sorted(v[0] for v in values) == [202, 429]
        current = self.otp(pending["email"])
        wrong = "000000" if current != "000000" else "111111"
        for _ in range(5):
            self.request("POST", "/api/auth/verify-email", None, {"email": pending["email"], "code": wrong}, 400)
        self.request("POST", "/api/auth/verify-email", None, {"email": pending["email"], "code": current}, 400)
        with self.rt.connect() as conn:
            failed = conn.execute("SELECT failed_attempts FROM email_verifications WHERE user_id=%s", (pending["id"],)).fetchone()[0]
        assert failed == 5
        return {"single_registration": True, "single_verify": True, "single_resend": True, "five_attempt_lockout": True}

    def otp_expiry_lock(self):
        import base64
        import hashlib
        import hmac
        pending = self.fx.new_user(verified=False)
        code = "123456"
        hashed = hmac.new(base64.b64decode(self.rt.otp_secret), (pending["email"] + "\n" + code).encode(), hashlib.sha256).hexdigest()
        with self.rt.connect() as conn:
            conn.execute("INSERT INTO email_verifications(user_id,code_hash,sent_at,expires_at,failed_attempts) "
                "VALUES(%s,%s,now()-interval '1 minute',now()+interval '1.5 seconds',0)", (pending["id"], hashed))
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.rt.connect() as lock:
                lock.execute("SELECT id FROM users WHERE id=%s FOR UPDATE", (pending["id"],))
                future = pool.submit(self.request, "POST", "/api/auth/verify-email", None,
                                     {"email": pending["email"], "code": code})
                blocked = False
                for _ in range(30):
                    with self.rt.connect() as conn:
                        blocked = conn.execute("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname=current_database() "
                            "AND wait_event_type='Lock' AND query ILIKE '%%FROM users%%FOR UPDATE%%')").fetchone()[0]
                    if blocked:
                        break
                    time.sleep(0.1)
                time.sleep(1.6)
            code, _ = future.result(timeout=45)
        assert blocked, "Could not observe verification waiting for the account lock"
        assert code == 400
        with self.rt.connect() as conn:
            assert conn.execute("SELECT email_verified FROM users WHERE id=%s", (pending["id"],)).fetchone()[0] is False
        return {"expired_while_waiting": True, "ttl_policy_unchanged": True}

    def rollback(self):
        user = self.fx.new_user()
        trip, _ = self.fx.new_trip(2)
        deletion = self.rt.connect()
        try:
            deletion.execute("DELETE FROM users WHERE id=%s", (user["id"],))
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.book, trip, user["id"])
                blocked = False
                for _ in range(100):
                    with self.rt.connect() as conn:
                        blocked = conn.execute("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname=current_database() "
                            "AND wait_event_type='Lock' AND query ILIKE '%%insert%%bookings%%')").fetchone()[0]
                    if blocked:
                        break
                    time.sleep(0.1)
                deletion.commit()
                code, _ = future.result(timeout=45)
            assert blocked, "Could not establish the FK-failure schedule; rollback is unverified"
            assert code == 500 and self.counts(trip)[:3] == (2, 0, 0)
            return {"schedule": "delete fixture user uncommitted; HTTP insert waits; commit deletion; FK failure", "seat_rollback": True}
        finally:
            deletion.close()

    def timeout_semantics(self):
        trip, _ = self.fx.new_trip(3)
        key = secrets.token_hex(16)
        with self.rt.connect() as lock:
            lock.execute("SELECT id FROM trips WHERE id=%s FOR UPDATE", (trip,))
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.book, trip, "USER", 1, None, 0.4, key)
                try:
                    future.result(timeout=5)
                    raise AssertionError("Expected a client timeout")
                except requests.Timeout:
                    pass
        for _ in range(100):
            if self.counts(trip)[1] == 1:
                break
            time.sleep(0.1)
        assert self.counts(trip)[:3] == (2, 1, 1)
        _, replay = self.book(trip, expected=201, key=key)
        self.book(trip, quantity=2, expected=409, key=key)
        with self.rt.connect() as conn:
            assert conn.execute("SELECT id FROM bookings WHERE trip_id=%s", (trip,)).fetchone()[0] == replay["id"]
        assert self.counts(trip)[:3] == (2, 1, 1)
        return {"client_timeout_can_commit": True, "same_key_replayed": True, "different_payload_rejected": True}

    def smtp_fault(self):
        self.rt.restart_app()
        self.rt.stop(self.rt.mail)
        email = secrets.token_hex(7) + "@acceptance.example"
        try:
            self.registration(email)
            with self.rt.connect() as conn:
                row = conn.execute("SELECT u.email_verified,count(o.user_id) FROM users u JOIN verification_outbox o ON o.user_id=u.id "
                    "WHERE email=%s AND o.finished_at IS NULL GROUP BY u.id", (email,)).fetchone()
            assert row == (False, 1)
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                with self.rt.connect() as conn:
                    retried = conn.execute("SELECT EXISTS(SELECT 1 FROM verification_outbox o JOIN users u ON u.id=o.user_id "
                        "WHERE u.email=%s AND o.attempts>0 AND o.lease_until IS NULL AND o.finished_at IS NULL)", (email,)).fetchone()[0]
                if retried:
                    break
                time.sleep(0.2)
            else:
                raise AssertionError("Worker did not schedule a retry during the SMTP outage")
        finally:
            self.rt.start_mail()
        self.request("POST", "/api/auth/verify-email", None, {"email": email, "code": self.otp(email)}, 204)
        return {"pending_account_recovered": True, "worker_retried_without_resend": True}

    def db_fault(self):
        self.rt.pg_command([self.rt.pgbin / "pg_ctl", "-D", self.rt.pgdir / "data", "-m", "fast", "-w", "stop"])
        code = None
        try:
            try:
                code, _ = self.request("GET", "/api/users/me", timeout=45)
            except requests.Timeout:
                code = "CLIENT_TIMEOUT"
            assert code == "CLIENT_TIMEOUT" or code >= 500
        finally:
            self.rt.pg_command([self.rt.pgbin / "pg_ctl", "-D", self.rt.pgdir / "data", "-l", self.rt.pgdir / "server.log",
                "-o", f"-p {self.rt.pg_port} -h 127.0.0.1 -k {self.rt.pgdir}", "-w", "start"])
        start = time.monotonic()
        for _ in range(60):
            try:
                self.request("GET", "/api/users/me", expected=200, timeout=5)
                return {"outage_response": code, "recovery_seconds": time.monotonic() - start}
            except (requests.RequestException, AssertionError):
                time.sleep(1)
        raise AssertionError("Backend did not recover after DB restart")

    def db_wait_recovery(self):
        """Hold a root row and observe real app lock/pool wait without guessing pool size."""
        trip, _ = self.fx.new_trip(100)
        users = self.fx.data["users"][:50]
        lock = self.rt.connect()
        observed = 0
        started = time.monotonic()
        try:
            lock.execute("SELECT id FROM trips WHERE id=%s FOR UPDATE", (trip,))
            with ThreadPoolExecutor(max_workers=len(users)) as pool:
                futures = [pool.submit(self.book, trip, uid, 1, None, 45) for uid in users]
                try:
                    for _ in range(50):
                        with self.rt.connect() as conn:
                            count = conn.execute("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                                "AND wait_event_type='Lock' AND application_name<>'acceptance_observer'").fetchone()[0]
                        observed = max(observed, count)
                        if observed >= min(2, len(users)):
                            break
                        time.sleep(0.1)
                    assert observed >= min(2, len(users)), "Could not establish multiple DB lock waiters"
                    time.sleep(2)
                finally:
                    lock.commit()
                values = [future.result(timeout=50) for future in futures]
        finally:
            lock.close()
        codes = Counter(code for code, _ in values)
        assert set(codes) <= {201, 503} and codes[201] > 0
        if len(users) > 8:
            assert codes[503] > 0
        assert self.counts(trip)[:3] == (100 - codes[201], codes[201], codes[201])
        self.request("GET", "/api/users/me", expected=200)
        return {"submitted": len(users), "observed_db_lock_waiters": observed, "codes": dict(codes),
                "elapsed_seconds": time.monotonic() - started, "completed_after_release": True,
                "pool_occupancy": "not exposed; no pool exhaustion claim"}

    def run(self):
        self.case("functional.auth", self.auth)
        self.case("functional.catalog_and_booking", self.catalog)
        self.case("functional.security_filters_profile", self.security)
        self.case("functional.default_rate_limit", self.rate_limit)
        self.case("concurrency.last_seats", self.concurrency)
        self.case("concurrency.cancel", self.cancel_races)
        self.case("concurrency.admin_booking", self.admin_races)
        self.case("concurrency.unique", self.unique_races)
        self.case("concurrency.assignment_status", self.assignment_races)
        self.case("concurrency.profile_atomicity", self.profile_race)
        self.case("concurrency.otp", self.otp_races)
        self.case("concurrency.otp_expiry_lock", self.otp_expiry_lock)
        if self.rt.config["runtime"]["enable_faults"]:
            self.case("fault.transaction_rollback", self.rollback)
            self.case("fault.timeout_retry", self.timeout_semantics)
            self.case("fault.smtp", self.smtp_fault)
            self.case("fault.db_lock_wait_recovery", self.db_wait_recovery)
            self.case("fault.postgres_restart", self.db_fault)
        else:
            self.results.append({"name": "faults", "status": "SKIPPED"})
        self.case("data.invariants", lambda: self.assert_data())
        missing = sorted(ENDPOINTS - self.covered)
        save(self.rt.root / "endpoint-coverage.json", {"expected": len(ENDPOINTS), "covered": len(ENDPOINTS & self.covered),
             "missing": missing, "status": "FAIL" if missing else "PASS"})
        save(self.rt.root / "acceptance.json", self.results)
        return self.results

    def assert_data(self):
        result = self.fx.verify()
        assert result["status"] == "PASS", result
        return result


def class_strings(data):
    """Read class constant-pool UTF8 strings without loading target bytecode."""
    if data[:4] != b"\xca\xfe\xba\xbe":
        raise ValueError("Not a Java class")
    count = struct.unpack_from(">H", data, 8)[0]
    i, offset, strings = 1, 10, []
    sizes = {3: 4, 4: 4, 5: 8, 6: 8, 7: 2, 8: 2, 9: 4, 10: 4, 11: 4, 12: 4,
             15: 3, 16: 2, 17: 4, 18: 4, 19: 2, 20: 2}
    while i < count:
        tag = data[offset]
        offset += 1
        if tag == 1:
            length = struct.unpack_from(">H", data, offset)[0]
            offset += 2
            strings.append(data[offset:offset + length].decode("utf-8", errors="replace"))
            offset += length
        else:
            offset += sizes[tag]
            if tag in (5, 6):
                i += 1
        i += 1
    return strings


def architecture(jar):
    violations, examined = [], 0
    prefix = "BOOT-INF/classes/com/example/busbooking/"
    with zipfile.ZipFile(jar) as archive:
        for name in archive.namelist():
            if not name.startswith(prefix + "business/") or not name.endswith(".class"):
                continue
            examined += 1
            for value in class_strings(archive.read(name)):
                if any(pattern in value for pattern in ("com/example/busbooking/api/", "com/example/busbooking/data/",
                    "com/example/busbooking/security/", "com/example/busbooking/notification/", "jakarta/persistence/", "jakarta/servlet/")):
                    violations.append({"class": name, "reference": value[:200]})
    return {"status": "FAIL" if violations else ("PASS" if examined else "UNKNOWN"),
            "examined_business_classes": examined, "violations": violations,
            "scope": "Constant-pool boundary check only; not global architectural equivalence"}
