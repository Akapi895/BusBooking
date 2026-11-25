"""Portable helpers; no network or subprocess effects at import time."""
import base64
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import time


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    # Windows readers can briefly hold a sharing lock; Linux rename is atomic immediately.
    for attempt in range(30):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 29:
                raise
            time.sleep(0.01)


def append(path, value):
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, default=str) + "\n")


def read_journal(path):
    """Salvage complete records after interruption; report every malformed row."""
    path = Path(path)
    records, invalid = [], []
    if path.exists():
        with open(path, encoding="utf-8") as stream:
            for number, line in enumerate(stream, 1):
                try:
                    records.append(json.loads(line))
                except ValueError:
                    invalid.append(number)
    return records, invalid


def jwt(user_id, secret, issuer="busbooking", ttl=86400, now=None):
    now = int(time.time() if now is None else now)
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).rstrip(b"=")
    parts = [encode({"alg": "HS256", "typ": "JWT"}), encode(
        {"sub": str(user_id), "iss": issuer, "iat": now, "exp": now + ttl})]
    signature = hmac.new(base64.b64decode(secret), b".".join(parts), hashlib.sha256).digest()
    return b".".join(parts + [base64.urlsafe_b64encode(signature).rstrip(b"=")]).decode()


def percentile(values, p):
    if not values:
        return None
    values = sorted(values)
    return values[max(0, math.ceil(len(values) * p) - 1)]


def histogram_percentile(histogram, p):
    total = sum(histogram.values())
    if not total:
        return None
    target = math.ceil(total * p)
    count = 0
    for bucket, number in sorted((float(k), v) for k, v in histogram.items()):
        count += number
        if count >= target:
            return bucket


def slot_permutation(size, seed):
    """O(1) bijection over a finite slot budget, spread across trips from the start."""
    if size < 1:
        raise ValueError("No fixture slots")
    multiplier = max(1, int(size * 0.61803398875))
    while math.gcd(multiplier, size) != 1:
        multiplier += 1
    return multiplier, seed % size


def slot_trip_index(number, trips, capacity, permutation):
    if not 0 <= number < trips * capacity:
        raise IndexError("Fixture slots exhausted")
    multiplier, offset = permutation
    return ((multiplier * number + offset) % (trips * capacity)) % trips


def redact(text, secrets):
    for value in sorted((v for v in secrets if v), key=len, reverse=True):
        text = text.replace(value, "[REDACTED]")
    return text


def effective_cpus():
    """Report quota and affinity separately; psutil's CPU% uses one core = 100%."""
    affinity = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count()
    quota = None
    try:
        fields = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if fields[0] != "max":
            quota = int(fields[0]) / int(fields[1])
    except (OSError, ValueError):
        try:
            q = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read_text())
            period = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read_text())
            quota = q / period if q > 0 else None
        except (OSError, ValueError):
            pass
    return {"logical": os.cpu_count(), "affinity": affinity, "quota": quota,
            "effective": min(affinity, quota) if quota else affinity}


def cgroup_snapshot():
    facts = {}
    for name in ("memory.max", "memory.current", "memory.events", "cpu.stat"):
        try:
            facts[name] = Path("/sys/fs/cgroup", name).read_text().strip()
        except OSError:
            facts[name] = None
    return facts


def validate_config(config):
    f, load = config["fixture"], config["load"]
    for key in ("users", "trips", "capacity"):
        if not isinstance(f[key], int) or f[key] < 1:
            raise ValueError("fixture." + key + " must be a positive integer")
    if not 1 < load["growth"] <= 3 or not 0 < load["relative_precision"] < 1:
        raise ValueError("Invalid adaptive search parameters")
    if load["think_min"] <= 0 or load["think_max"] < load["think_min"]:
        raise ValueError("Positive, ordered think times required for fixture budgeting")
    for key in ("initial_vu", "spawn_rate", "measure_seconds", "confirm_seconds", "confirm_repeats",
                "workload_budget_seconds", "total_budget_seconds", "read_timeout", "drain_seconds"):
        if load[key] <= 0:
            raise ValueError("load." + key + " must be positive")
    if load["drain_seconds"] <= load["connect_timeout"] + load["read_timeout"]:
        raise ValueError("Drain must exceed connect + read timeout")
    if set(config["workloads"]) - {"read", "write", "mixed", "hotspot"}:
        raise ValueError("Unknown workload")
    if config.get("profile") not in ("acceptance", "smoke"):
        raise ValueError("profile must be acceptance or smoke")
    if config["profile"] == "acceptance" and (config["concurrency"]["rounds"] < 100 or load["confirm_repeats"] < 3):
        raise ValueError("Reduced rounds/repeats require profile: smoke; never claim full acceptance")
    if f["users"] < max(config["concurrency"]["bursts"]):
        raise ValueError("Need distinct fixture accounts for the largest concurrency burst")
    if not 0 <= load["max_unexpected_error_ratio"] <= 1:
        raise ValueError("Invalid error ratio")
    if load["open_pacing_seconds"] <= 0 or load["max_rsd_pct"] <= 0 or not all(x > 0 for x in load["open_rate_fractions"]):
        raise ValueError("Open-model pacing, rate fractions and max_rsd_pct must be positive")
    return config
