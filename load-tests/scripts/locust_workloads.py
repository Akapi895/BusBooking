"""Imported by Locust child processes only. Settings come from runner-owned files."""
import itertools
import json
import math
import os
from pathlib import Path
import random
import time
from collections import Counter, defaultdict

import gevent
from locust import HttpUser, between, events, task
from locust.exception import StopUser
import psutil

from bbtest.common import append, jwt, save, slot_permutation, slot_trip_index
from bbtest.contracts import booking_valid


SETTINGS = json.loads(Path(os.environ["BB_SETTINGS"]).read_text(encoding="utf-8"))
FIXTURE = json.loads(Path(SETTINGS["fixture_path"]).read_text(encoding="utf-8"))
LOAD = SETTINGS["load"]
INDEX, WORKERS = SETTINGS["worker_index"], SETTINGS["workers"]
DIRECTORY = Path(SETTINGS["directory"])
random.seed(SETTINGS["seed"] + INDEX)
USERS = iter(FIXTURE["users"][INDEX::WORKERS])
TRIPS = FIXTURE["trips"][INDEX::WORKERS]
random.shuffle(TRIPS)
SLOTS = itertools.count()
PERMUTATION = slot_permutation(len(TRIPS) * FIXTURE["capacity"], SETTINGS["seed"] + INDEX)
STATS = defaultdict(lambda: {"started": 0, "requests": 0, "unexpected_errors": 0, "assertions": 0,
                           "expected_rejections": 0, "completions_in_window": 0, "bytes": 0,
                           "successful_in_window": 0, "rejected_in_window": 0,
                           "status_codes": Counter(), "read": Counter(), "write": Counter(), "endpoints": {}})
SCHEDULE = None
EXHAUSTED = False
ACKNOWLEDGED = 0
LAGS, CPU = [], []
VALIDITY = defaultdict(lambda: {"samples": 0, "lag_bad": 0, "cpu_bad": 0, "vu_bad": 0})
JOURNAL = open(DIRECTORY / f"bookings-{INDEX}.csv", "a", encoding="utf-8", buffering=1024 * 1024)


def current_phase():
    if SCHEDULE is None:
        return "ramp"
    now = time.time()
    if now < SCHEDULE["measure_start"]:
        return "warmup"
    return "measure" if now < SCHEDULE["measure_end"] else "drain"


def slot(hotspot=False):
    global EXHAUSTED
    number = next(SLOTS)
    # Disjoint trips per worker for normal writes. Hotspot is intentionally shared.
    if hotspot:
        trips = FIXTURE["trips"]
        position = number // 100
    else:
        trips = TRIPS
        try:
            position = slot_trip_index(number, len(trips), FIXTURE["capacity"], PERMUTATION)
        except IndexError:
            EXHAUSTED = True
            raise StopUser()
    if position >= len(trips):
        EXHAUSTED = True
        raise StopUser()
    return trips[position]["id"]


@events.request.add_listener
def completed(request_type, name, response_time, response_length, response=None,
              context=None, exception=None, **kwargs):
    global ACKNOWLEDGED
    context = context or {}
    if "phase" not in context:
        return
    keys = [context["phase"]] + ([context["segment"]] if "segment" in context else [])
    for key in keys:
        row = STATS[key]
        row["requests"] += 1
        row["bytes"] += response_length or 0
        row[context["family"]][str(math.ceil(response_time))] += 1
        code = response.status_code if response is not None else 0
        row["status_codes"][str(code)] += 1
        endpoint = row["endpoints"].setdefault(name, {"requests": 0, "errors": 0, "histogram_ms": Counter()})
        endpoint["requests"] += 1
        endpoint["histogram_ms"][str(math.ceil(response_time))] += 1
        if context.get("expected_rejection"):
            row["expected_rejections"] += 1
        elif exception is not None:
            row["unexpected_errors"] += 1
            endpoint["errors"] += 1
        if context.get("assertion"):
            row["assertions"] += 1
        end = context.get("segment_end") if key.startswith("segment-") else (SCHEDULE or {}).get("measure_end", 0)
        if context["phase"] == "measure" and time.time() <= end:
            row["completions_in_window"] += 1
            row["successful_in_window"] += exception is None and not context.get("expected_rejection")
            row["rejected_in_window"] += bool(context.get("expected_rejection"))
    if context.get("booking_ack"):
        ACKNOWLEDGED += 1


def dump(environment, final=False):
    value = {"epoch": time.time(), "worker_index": INDEX, "user_count": environment.runner.user_count,
             "phases": dict(STATS), "fixture_exhausted": EXHAUSTED, "acknowledged": ACKNOWLEDGED,
             "lag_ms": LAGS[-1] if LAGS else 0, "cpu_one_core_pct": CPU[-1] if CPU else 0,
             "lag_samples": len(LAGS), "lag_bad_samples": sum(x > LOAD["generator_max_lag_ms"] for x in LAGS),
             "cpu_bad_samples": sum(x > LOAD["generator_max_cpu_per_core"] for x in CPU),
             "validity": dict(VALIDITY),
             "complete": final}
    if not final:
        value["phases"] = {phase: {k: v for k, v in row.items() if k not in ("read", "write", "endpoints")}
                           for phase, row in STATS.items()}
    save(DIRECTORY / f"worker-{INDEX}.json", value)
    if not final:
        append(DIRECTORY / f"worker-{INDEX}-history.jsonl", value)


@events.init.add_listener
def monitor(environment, **kwargs):
    def loop():
        global SCHEDULE
        process = psutil.Process()
        process.cpu_percent()
        ready = False
        last_shape = None
        while True:
            started = time.monotonic()
            gevent.sleep(1)
            LAGS.append(max(0, (time.monotonic() - started - 1) * 1000))
            CPU.append(process.cpu_percent())
            schedule_path = DIRECTORY / "schedule.json"
            if SCHEDULE is None and schedule_path.exists():
                SCHEDULE = json.loads(schedule_path.read_text())
            phase = current_phase()
            sample_keys = [phase]
            target = SETTINGS["vu"]
            if phase == "measure" and SCHEDULE.get("sequence"):
                elapsed = time.time() - SCHEDULE["measure_start"]
                selected = max(i for i, step in enumerate(SCHEDULE["sequence"]) if step["at"] <= elapsed)
                sample_keys.append(f"segment-{selected}")
                step_vu = SCHEDULE["sequence"][selected]["vu"]
                target = step_vu // WORKERS + (INDEX < step_vu % WORKERS)
            for key in sample_keys:
                VALIDITY[key]["samples"] += 1
                VALIDITY[key]["lag_bad"] += LAGS[-1] > LOAD["generator_max_lag_ms"]
                VALIDITY[key]["cpu_bad"] += CPU[-1] > LOAD["generator_max_cpu_per_core"]
                VALIDITY[key]["vu_bad"] += environment.runner.user_count != target
            if not ready and environment.runner.user_count == SETTINGS["vu"]:
                save(DIRECTORY / f"ready-{INDEX}.json", {"epoch": time.time(), "vu": SETTINGS["vu"]})
                ready = True
            if SCHEDULE and SCHEDULE.get("sequence"):
                elapsed = time.time() - SCHEDULE["measure_start"]
                for i, step in enumerate(SCHEDULE["sequence"]):
                    if step["at"] <= elapsed and last_shape != i and not any(
                            later["at"] <= elapsed for later in SCHEDULE["sequence"][i + 1:]):
                        target = step["vu"] // WORKERS + (INDEX < step["vu"] % WORKERS)
                        environment.runner.start(target, max(1, LOAD["spawn_rate"] / WORKERS))
                        last_shape = i
            dump(environment)
            if SCHEDULE and time.time() >= SCHEDULE["measure_end"] + LOAD["drain_seconds"]:
                environment.runner.quit()
                break
    gevent.spawn(loop)


@events.quitting.add_listener
def finished(environment, **kwargs):
    JOURNAL.flush()
    JOURNAL.close()
    dump(environment, final=True)


class AcceptanceUser(HttpUser):
    wait_time = between(LOAD["think_min"], LOAD["think_max"])

    def on_start(self):
        global EXHAUSTED
        try:
            self.uid = next(USERS)
        except StopIteration:
            EXHAUSTED = True
            raise StopUser()
        self.token = jwt(self.uid, os.environ["BB_JWT_SECRET"])
        self.owned = []
        self.sequence = 0

    def call(self, method, path, family="read", body=None, authenticated=False, expected=200, validate=None, hot=False):
        phase = current_phase()
        if phase == "drain":
            gevent.sleep(0.1)
            return None
        context = {"phase": phase, "family": family}
        STATS[phase]["started"] += 1
        if phase == "measure" and SCHEDULE.get("sequence"):
            elapsed = time.time() - SCHEDULE["measure_start"]
            for i, step in enumerate(SCHEDULE["sequence"]):
                if step["at"] <= elapsed:
                    context["segment"] = f"segment-{i}"
                    context["segment_end"] = SCHEDULE["measure_start"] + (
                        SCHEDULE["sequence"][i + 1]["at"] if i + 1 < len(SCHEDULE["sequence"]) else
                        SCHEDULE["measure_end"] - SCHEDULE["measure_start"])
            STATS[context["segment"]]["started"] += 1
        name = method + " " + ("/api/trips/{id}" if path.startswith("/api/trips/") else
            "/api/bookings/{id}" if path.startswith("/api/bookings/") else path.split("?", 1)[0])
        if "?" in path:
            name += " [filtered]"
        headers = {"Authorization": "Bearer " + self.token} if authenticated else {}
        if method == "POST" and path == "/api/bookings":
            headers["Idempotency-Key"] = body["passengerName"]
        with self.client.request(method, path, name=name, json=body, headers=headers,
                timeout=(LOAD["connect_timeout"], LOAD["read_timeout"]), catch_response=True, context=context) as response:
            context = response.request_meta["context"]
            try:
                data = response.json() if response.content else None
            except ValueError:
                data = None
            exhausted = response.status_code == 409 and isinstance(data, dict) and data.get("error") == "INSUFFICIENT_SEATS"
            busy = (response.status_code == 503 and isinstance(data, dict)
                    and data.get("error") == "SERVICE_UNAVAILABLE" and response.headers.get("Retry-After") == "1")
            if hot and (exhausted or busy):
                context["expected_rejection"] = True
                response.success()
            elif response.status_code != expected:
                response.failure(f"HTTP {response.status_code}")
            elif validate and not validate(data):
                context["assertion"] = True
                response.failure("CONTRACT_ASSERTION")
            else:
                response.success()
                if method == "POST" and path == "/api/bookings":
                    context["booking_ack"] = True
                    self.owned.append(data["id"])
                    # Compact all-phase acknowledgement journal, no tokens or response bodies.
                    JOURNAL.write(f"{data['id']},{self.uid},{phase}\n")
            return data

    def read(self):
        trip = random.choice(TRIPS)
        choice = random.random()
        if choice < 0.55:
            path = f"/api/trips?originId={trip['origin']}&destinationId={trip['destination']}&departureDate={trip['date']}"
            self.call("GET", path, validate=lambda data: isinstance(data, list) and len(data) <= 20 and all(
                x.get("departureTime", "")[:10] == trip["date"] and x.get("routeId") == trip["route"] for x in data))
        elif choice < 0.90:
            self.call("GET", f"/api/trips/{trip['id']}", validate=lambda data: isinstance(data, dict) and data.get("id") == trip["id"])
        elif choice < 0.95:
            self.call("GET", "/api/trips", validate=lambda data: isinstance(data, list) and len(data) <= 20 and all(
                item.get("status") == "SCHEDULED" and item.get("availableSeats", 0) > 0 for item in data))
        else:
            self.call("GET", "/api/locations?q=Load", validate=lambda data: isinstance(data, list) and len(data) > 0)

    def write(self, hot=False):
        trip = slot(hot)
        self.sequence += 1
        body = {"tripId": trip, "passengerName": SETTINGS["marker"] + f"-{self.uid}-{self.sequence}",
                "passengerPhone": "0901234567", "quantity": 1}
        self.call("POST", "/api/bookings", "write", body, True, 201,
                  lambda data: booking_valid(data, self.uid, trip, 1, FIXTURE["price"]), hot)

    @task
    def exercise(self):
        if current_phase() == "drain":
            gevent.sleep(0.1)
            return
        workload = SETTINGS["workload"]
        if workload == "read":
            self.read()
        elif workload == "write":
            self.write()
        elif workload == "hotspot":
            self.write(True)
        else:
            choice = random.random()
            if choice < 0.65:
                self.read()
            elif choice < 0.85:
                self.write()
            elif choice < 0.95:
                self.call("GET", "/api/users/me/bookings", authenticated=True,
                          validate=lambda data: isinstance(data, list))
            elif self.owned:
                booking = self.owned.pop(0)
                self.call("DELETE", f"/api/bookings/{booking}", "write", authenticated=True,
                          validate=lambda data: isinstance(data, dict) and data.get("id") == booking and data.get("status") == "CANCELLED")
            else:
                self.read()
