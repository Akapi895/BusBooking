"""Compare one and two local BusBooking JVMs on the same 40-seat burst."""

import argparse
import base64
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
import os
from pathlib import Path
import secrets
import socket
import subprocess
from threading import Barrier
import time

import psycopg
from psycopg import sql
import requests

from bbtest.common import digest, jwt, percentile, save
from bbtest.fixtures import Fixtures


CAPACITY = 40
EXPECTED_REJECTIONS = {
    (409, "INSUFFICIENT_SEATS"),
    (503, "SERVICE_UNAVAILABLE"),
}


class FixtureRuntime:
    def __init__(self, root, dsn, clients):
        self.root = root
        self.dsn = dsn
        self.config = {"fixture": {"users": clients, "trips": 100, "capacity": CAPACITY}}

    def connect(self):
        return psycopg.connect(**self.dsn, connect_timeout=5)


@contextmanager
def scratch_database(admin):
    name = "bb_hotspot_" + secrets.token_hex(8)
    with psycopg.connect(**admin, autocommit=True, connect_timeout=5) as connection:
        database = sql.Identifier(name)
        connection.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(database))
        try:
            yield dict(admin, dbname=name)
        finally:
            connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(database))


@contextmanager
def backend(jar, dsn, key, log_path):
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    inherited_prefixes = (
        "SPRING_", "SERVER_", "DB_", "JWT_", "EMAIL_", "OTP_", "SMTP_", "AUTH_",
        "BOOKING_", "BOOTSTRAP_", "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS",
    )
    env = {name: value for name, value in os.environ.items() if not name.startswith(inherited_prefixes)}
    env.update(
        SPRING_PROFILES_ACTIVE="dev",
        SERVER_PORT=str(port),
        SERVER_ADDRESS="127.0.0.1",
        DB_URL=f"jdbc:postgresql://127.0.0.1:{dsn['port']}/{dsn['dbname']}",
        DB_USERNAME=dsn["user"],
        DB_PASSWORD=dsn["password"],
        JWT_SECRET=key,
        EMAIL_OTP_SECRET=base64.b64encode(secrets.token_bytes(32)).decode(),
        OTP_OUTBOX_SECRET=base64.b64encode(secrets.token_bytes(32)).decode(),
        BOOTSTRAP_SUPER_ADMIN_ENABLED="false",
    )
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            ["java", "-Duser.timezone=Asia/Ho_Chi_Minh", "-Xmx512m", "-jar", str(jar)],
            env=env, stdout=log, stderr=subprocess.STDOUT,
        )
    try:
        deadline = time.monotonic() + 75
        with requests.Session() as probe:
            probe.trust_env = False
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"Backend exited during startup. See {log_path}.")
                try:
                    if probe.get(url + "/api/trips?size=1", timeout=1).status_code == 200:
                        break
                except requests.RequestException:
                    pass
                time.sleep(0.2)
            else:
                raise RuntimeError(f"Backend did not become ready. See {log_path}.")
        yield url
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


def send_burst(urls, users, trip_id, key):
    started = []
    gate = Barrier(len(users), action=lambda: started.append(time.perf_counter()), timeout=20)

    def submit(index, user_id):
        address = urls[index % len(urls)]
        payload = {
            "tripId": trip_id,
            "passengerName": f"Hotspot Rider {index + 1}",
            "passengerPhone": "0901234567",
            "quantity": 1,
        }
        headers = {"Authorization": "Bearer " + jwt(user_id, key), "Idempotency-Key": f"burst-{index}"}
        with requests.Session() as client:
            client.trust_env = False
            gate.wait()
            before = time.perf_counter()
            try:
                response = client.post(address + "/api/bookings", json=payload, headers=headers, timeout=25)
            except requests.RequestException:
                return 0, "TRANSPORT_ERROR", None, (time.perf_counter() - before) * 1000
            elapsed = (time.perf_counter() - before) * 1000
            try:
                body = response.json()
            except requests.exceptions.JSONDecodeError:
                body = {}
            if not isinstance(body, dict):
                body = {}
            return response.status_code, body.get("error"), body.get("id"), elapsed

    with ThreadPoolExecutor(max_workers=len(users)) as pool:
        futures = [pool.submit(submit, index, user_id) for index, user_id in enumerate(users)]
        rows = [future.result() for future in futures]
        duration = time.perf_counter() - started[0]
    return rows, duration


def summarize(rows, elapsed, available, persisted_ids):
    acknowledged = [booking_id for status, _, booking_id, _ in rows if status == 201]
    unexpected = Counter((status, error) for status, error, _, _ in rows
                         if status != 201 and (status, error) not in EXPECTED_REJECTIONS)
    latencies = [ms for _, _, _, ms in rows]
    consistent = (
        bool(persisted_ids)
        and 0 <= available <= CAPACITY
        and len(acknowledged) == len(set(acknowledged))
        and set(acknowledged) == set(persisted_ids)
        and len(persisted_ids) + available == CAPACITY
    )
    return {
        "status_counts": dict(Counter(str(status) for status, _, _, _ in rows)),
        "p95_ms": round(percentile(latencies, 0.95), 2),
        "p99_ms": round(percentile(latencies, 0.99), 2),
        "bookings_per_second": round(len(acknowledged) / elapsed, 2),
        "elapsed_seconds": round(elapsed, 3),
        "confirmed_bookings": len(persisted_ids),
        "available_seats": available,
        "unexpected_responses": {f"{code} {error}": count for (code, error), count in unexpected.items()},
        "pass": consistent and not unexpected,
    }


def scenario(jar, root, admin, clients, backend_count):
    root.mkdir()
    key = base64.b64encode(secrets.token_bytes(32)).decode()
    with scratch_database(admin) as dsn, ExitStack() as processes:
        urls = [processes.enter_context(backend(jar, dsn, key, root / "backend-1.log"))]
        runtime = FixtureRuntime(root, dsn, clients)
        fixture = Fixtures(runtime).prepare(snapshot=False)
        trip_id = fixture["trips"][0]["id"]
        if backend_count == 2:
            urls.append(processes.enter_context(backend(jar, dsn, key, root / "backend-2.log")))
        rows, elapsed = send_burst(urls, fixture["users"], trip_id, key)
        with runtime.connect() as connection:
            available = connection.execute("SELECT available_seats FROM trips WHERE id = %s", (trip_id,)).fetchone()[0]
            ids = [row[0] for row in connection.execute(
                "SELECT id FROM bookings WHERE trip_id = %s AND status = 'CONFIRMED'", (trip_id,)
            ).fetchall()]
        return summarize(rows, elapsed, available, ids)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--clients", type=int, default=160)
    parser.add_argument("--pg-port", type=int, default=55433)
    parser.add_argument("--pg-user", default="busbooking_test")
    args = parser.parse_args()
    if not args.jar.is_file():
        parser.error("Build or provide an executable BusBooking JAR.")
    if not 1 <= args.clients <= 256 or not 1 <= args.pg_port <= 65535:
        parser.error("Clients must be 1–256 and the PostgreSQL port must be valid.")
    if not os.environ.get("PGPASSWORD"):
        parser.error("Set PGPASSWORD for the local scratch PostgreSQL cluster.")
    admin = dict(host="127.0.0.1", port=args.pg_port, dbname="postgres",
                 user=args.pg_user, password=os.environ["PGPASSWORD"])
    args.output.mkdir(parents=True, exist_ok=False)
    summary = {
        "jar_sha256": digest(args.jar),
        "clients": args.clients,
        "capacity": CAPACITY,
        "dispatch": "round robin to loopback HTTP ports",
        "runs": {},
    }
    for count in (1, 2):
        summary["runs"][str(count)] = scenario(
            args.jar.resolve(), args.output / f"{count}-backend", admin, args.clients, count,
        )
        save(args.output / "summary.json", summary)
    return 0 if all(run["pass"] for run in summary["runs"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
