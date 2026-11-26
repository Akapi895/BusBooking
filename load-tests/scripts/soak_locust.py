"""Long mixed load through Nginx: filtered search, hold + confirm, abandoned holds, cancellations.

Started by run_soak.py, which passes accounts and settings in the JSON file named by BB_SOAK.
409 (sold out) and 503 (busy, with Retry-After) on booking are expected rejections, not errors.
"""
import datetime
import itertools
import json
import os
import random
import uuid
from collections import Counter

from locust import HttpUser, between, events, task

from bbtest.common import jwt

CFG = json.loads(open(os.environ["BB_SOAK"], encoding="utf-8").read())
ACCOUNTS = itertools.cycle(CFG["user_ids"])
STATUS = Counter()  # "<request name> <status>" -> count
EXPECTED = {"POST /api/bookings": {201, 409, 503},
            "POST /api/bookings/{id}/confirm": {200},
            # 400: the customer cancellation window (30 min before departure) has closed.
            "DELETE /api/bookings/{id}": {200, 400}}


class Customer(HttpUser):
    wait_time = between(CFG["think_min"], CFG["think_max"])

    def on_start(self):
        self.headers = {"Authorization": "Bearer " + jwt(next(ACCOUNTS), CFG["jwt_secret"], ttl=6 * 3600)}
        self.bookable = []

    def call(self, method, path, name, expected=frozenset({200}), **kwargs):
        with self.client.request(method, path, name=name, headers={**self.headers, **kwargs.pop("headers", {})},
                                 catch_response=True, **kwargs) as response:
            STATUS[f"{name} {response.status_code}"] += 1
            if response.status_code in EXPECTED.get(name, expected):
                response.success()
            else:
                response.failure(f"unexpected {response.status_code}")
            return response

    @task(6)
    def search(self):
        origin, destination = random.choice(CFG["routes"])
        day = datetime.date.fromisoformat(CFG["today"]) + datetime.timedelta(days=random.randint(0, 13))
        response = self.call("GET", f"/api/trips?originId={origin}&destinationId={destination}&departureDate={day}",
                             "GET /api/trips?filter")
        if response.status_code == 200:
            self.bookable = [trip["id"] for trip in response.json() if trip["availableSeats"] > 0]

    @task(1)
    def my_bookings(self):
        self.call("GET", "/api/users/me/bookings", "GET /api/users/me/bookings")

    @task(2)
    def book(self):
        if not self.bookable:
            return
        body = {"tripId": random.choice(self.bookable), "passengerName": "Soak Test",
                "passengerPhone": "0912345678", "quantity": random.randint(1, 2)}
        response = self.call("POST", "/api/bookings", "POST /api/bookings", json=body,
                             headers={"Idempotency-Key": uuid.uuid4().hex})
        if response.status_code != 201 or random.random() < CFG["abandon_ratio"]:
            return  # an abandoned hold must lapse and give its seats back
        booking = response.json()["id"]
        self.call("POST", f"/api/bookings/{booking}/confirm", "POST /api/bookings/{id}/confirm")
        if random.random() < CFG["cancel_ratio"]:
            self.call("DELETE", f"/api/bookings/{booking}", "DELETE /api/bookings/{id}")


@events.test_stop.add_listener
def save_statuses(**_):
    # One file per Locust process; run_soak.py adds them up.
    with open(os.path.join(CFG["status_dir"], f"statuses-{os.getpid()}.json"), "w", encoding="utf-8") as out:
        json.dump(dict(sorted(STATUS.items())), out, indent=2)
