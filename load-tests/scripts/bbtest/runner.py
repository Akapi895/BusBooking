"""Adaptive execution, isolated snapshots, phase-aware statistics, bounded evidence."""
from collections import Counter
import json
import math
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

from .adaptive import Search, classify, INVALID
from .common import append, effective_cpus, histogram_percentile, save
from .telemetry import Collector, diagnostic


def aggregate(workers, seconds, load, phase_name="measure"):
    result = {"requests": 0, "unexpected_errors": 0, "assertions": 0, "expected_rejections": 0,
              "completions_in_window": 0, "started": 0, "bytes": 0, "acknowledged": 0,
              "successful_in_window": 0, "rejected_in_window": 0,
              "complete": bool(workers) and all(w.get("complete") for w in workers),
              "fixture_exhausted": any(w.get("fixture_exhausted") for w in workers),
              "generator_limited": False, "status_codes": Counter(), "endpoints": {}}
    histograms = {"read": Counter(), "write": Counter()}
    for worker in workers:
        phase = worker.get("phases", {}).get(phase_name, {})
        for key in ("requests", "unexpected_errors", "assertions", "expected_rejections", "completions_in_window", "started", "bytes", "successful_in_window", "rejected_in_window"):
            result[key] += phase.get(key, 0)
        result["all_phase_assertions"] = result.get("all_phase_assertions", 0) + sum(
            worker.get("phases", {}).get(key, {}).get("assertions", 0) for key in ("ramp", "warmup", "measure"))
        result["acknowledged"] += worker.get("acknowledged", 0)
        result["status_codes"].update(phase.get("status_codes", {}))
        for family in histograms:
            histograms[family].update(phase.get(family, {}))
        for name, endpoint in phase.get("endpoints", {}).items():
            dest = result["endpoints"].setdefault(name, {"requests": 0, "errors": 0, "histogram_ms": Counter()})
            dest["requests"] += endpoint["requests"]
            dest["errors"] += endpoint["errors"]
            dest["histogram_ms"].update(endpoint["histogram_ms"])
        validity = worker.get("validity", {}).get(phase_name, {})
        samples = validity.get("samples", 0)
        fraction = load["generator_max_lag_fraction"]
        if not samples or validity.get("lag_bad", 0) / max(samples, 1) > fraction or validity.get("cpu_bad", 0) / max(samples, 1) > fraction:
            result["generator_limited"] = True
        if phase_name == "measure" and validity.get("vu_bad", 0) / max(samples, 1) > fraction:
            result["target_not_maintained"] = True
    for family, histogram in histograms.items():
        result[family + "_p95_ms"] = histogram_percentile(histogram, 0.95)
        result[family + "_p99_ms"] = histogram_percentile(histogram, 0.99)
        result[family + "_histogram_ms"] = histogram
    for endpoint in result["endpoints"].values():
        endpoint["p95_ms"] = histogram_percentile(endpoint["histogram_ms"], 0.95)
        endpoint["p99_ms"] = histogram_percentile(endpoint["histogram_ms"], 0.99)
    result["pending"] = result["started"] - result["requests"]
    result["completed_rps"] = result["completions_in_window"] / seconds
    result["successful_rps"] = result["successful_in_window"] / seconds
    result["expected_rejection_rps"] = result["rejected_in_window"] / seconds
    result["start_rps"] = result["started"] / seconds
    result["error_ratio"] = result["unexpected_errors"] / max(1, result["requests"])
    result["latency_scope"] = "requests starting in measure; includes drained completions/timeouts; right-censored requests remain pending"
    return result


class Runner:
    def __init__(self, rt, fixtures, scripts):
        self.rt, self.fx, self.scripts = rt, fixtures, Path(scripts)
        self.load = rt.config["load"]
        self.stages, self.searches = [], {}
        self.deadline = time.monotonic() + self.load["total_budget_seconds"]
        self.phase_deadline = None

    def remaining(self):
        return min(self.deadline, self.phase_deadline or self.deadline) - time.monotonic()

    def reconcile(self, directory, marker, acknowledged):
        idle = 0
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            with self.rt.connect() as conn:
                active = conn.execute("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                    "AND application_name<>'acceptance_observer' AND state IN ('active','idle in transaction')").fetchone()[0]
            idle = idle + 1 if active == 0 else 0
            if idle >= 3:
                break
            time.sleep(0.2)
        if idle < 3:
            return {"status": "UNKNOWN", "reason": "Server transactions still active after drain"}
        oracle = self.fx.verify(marker, acknowledged)
        # The oracle checks acknowledged IDs/owners, not just aggregate counts.
        with self.rt.connect() as conn:
            conn.execute("CREATE TEMP TABLE acceptance_acks(id bigint PRIMARY KEY,user_id bigint)")
            with conn.cursor().copy("COPY acceptance_acks(id,user_id) FROM STDIN") as copy:
                for path in directory.glob("bookings-*.csv"):
                    with open(path, encoding="utf-8") as stream:
                        for line in stream:
                            booking_id, uid, _phase = line.strip().split(",")
                            copy.write_row((int(booking_id), int(uid)))
            oracle["acknowledgements_missing_or_wrong_owner"] = conn.execute(
                "SELECT count(*) FROM acceptance_acks a LEFT JOIN bookings b ON b.id=a.id "
                "WHERE b.id IS NULL OR b.user_id<>a.user_id OR b.passenger_name NOT LIKE %s", (marker + "%",)).fetchone()[0]
            if oracle["acknowledgements_missing_or_wrong_owner"]:
                oracle["status"] = "FAIL"
            oracle["journal_acknowledgements"] = conn.execute("SELECT count(*) FROM acceptance_acks").fetchone()[0]
            if oracle["journal_acknowledgements"] != acknowledged and oracle["status"] != "FAIL":
                oracle["status"] = "UNKNOWN"
                oracle["reason"] = "Acknowledgement journal incomplete"
        return oracle

    def stage(self, workload, vu, seconds=None, label="discovery", profiled=False, sequence=None, worker_override=None):
        seconds = seconds or self.load["measure_seconds"]
        max_vu = max([vu] + [step["vu"] for step in sequence or []])
        if max_vu > len(self.fx.data["users"]):
            return {"workload": workload, "vu": vu, "label": label, "status": "FIXTURE_EXHAUSTED",
                    "reason": "Not enough distinct fixture accounts; increase fixture.users for a NEW experiment"}
        workers = min(vu, worker_override or max(1, int(effective_cpus()["effective"] // 2)))
        warmup = self.load.get("discovery_warmup_seconds", self.load["warmup_seconds"]) if label in (
            "discovery", "refine", "overload", "generator-recheck") else self.load["warmup_seconds"]
        expected_wall = vu / self.load["spawn_rate"] + warmup + self.load["settle_seconds"] + seconds + self.load["drain_seconds"] + 90
        if self.remaining() < expected_wall:
            return {"workload": workload, "vu": vu, "label": label, "status": "BUDGET_EXHAUSTED"}
        directory = self.rt.root / "stages" / f"{len(self.stages):03d}-{workload}-{label}-u{vu}"
        directory.mkdir(parents=True)
        self.rt.restore()
        marker = "lt" + secrets.token_hex(6)
        processes, handles = [], []
        collector = Collector(self.rt, directory).start()
        start = time.monotonic()
        schedule = None
        reason = None
        profiling = None
        try:
            for index in range(workers):
                target = vu // workers + (index < vu % workers)
                settings = {"fixture_path": str(self.rt.root / "fixture.json"), "load": self.load,
                    "directory": str(directory), "worker_index": index, "workers": workers, "vu": target,
                    "workload": workload, "seed": self.rt.config["seed"], "marker": marker}
                path = directory / f"settings-{index}.json"
                save(path, settings)
                env = os.environ.copy()
                env.update(BB_SETTINGS=str(path), BB_JWT_SECRET=self.rt.secret, PYTHONUNBUFFERED="1")
                handle = open(directory / f"locust-{index}.log", "w", encoding="utf-8")
                handles.append(handle)
                processes.append(subprocess.Popen([sys.executable, "-m", "locust", "-f", str(self.scripts / "locust_workloads.py"),
                    "--headless", "--host", self.rt.url, "-u", str(target),
                    "-r", str(max(1, self.load["spawn_rate"] / workers)), "--only-summary",
                    "--stop-timeout", str(self.load["drain_seconds"])], env=env, stdout=handle, stderr=handle))
            ramp_deadline = time.monotonic() + vu / self.load["spawn_rate"] + 60
            while not all((directory / f"ready-{i}.json").exists() for i in range(workers)):
                if any(p.poll() is not None for p in processes) or time.monotonic() > ramp_deadline:
                    reason = "INCOMPLETE"
                    break
                time.sleep(1)
            if not reason:
                now = time.time()
                begin = now + warmup + self.load["settle_seconds"]
                schedule = {"measure_start": begin, "measure_end": begin + seconds,
                            "sequence": sequence, "target_vu": vu}
                save(directory / "schedule.json", schedule)
                bad_windows = 0
                previous = (0, 0)
                while any(p.poll() is None for p in processes):
                    if self.rt.app.poll() is not None:
                        reason = "OVERLOAD"
                        break
                    if time.monotonic() - start > expected_wall or self.remaining() <= 0:
                        reason = "INCOMPLETE"
                        break
                    if profiled and profiling is None and time.time() >= begin:
                        profiling = diagnostic(self.rt, directory / "diagnostic", min(60, int(seconds)))
                    snapshots = self.worker_files(directory, workers)
                    if any(s.get("fixture_exhausted") for s in snapshots):
                        reason = "FIXTURE_EXHAUSTED"
                        break
                    totals = (sum(s.get("phases", {}).get("measure", {}).get("requests", 0) for s in snapshots),
                              sum(s.get("phases", {}).get("measure", {}).get("unexpected_errors", 0) for s in snapshots))
                    if totals[0] - previous[0] >= 20:
                        ratio = (totals[1] - previous[1]) / (totals[0] - previous[0])
                        bad_windows = bad_windows + 1 if ratio >= self.load["abort_error_ratio"] else 0
                        previous = totals
                    if bad_windows >= self.load["abort_error_windows"] and not sequence:
                        reason = "OVERLOAD"
                        break
                    time.sleep(2)
        finally:
            # Signal all generators before waiting for any one of them to drain.
            for proc in processes:
                if proc.poll() is None:
                    proc.terminate()
            for proc in processes:
                self.rt.stop(proc)
            for handle in handles:
                handle.close()
            collector.stop()
        snapshots = self.worker_files(directory, workers)
        stats = aggregate(snapshots, seconds, self.load)
        stats["complete"] = stats["complete"] and len(snapshots) == workers and schedule is not None
        if sequence:
            # Shaped stages intentionally include ramp intervals; verify each segment below instead.
            stats.pop("target_not_maintained", None)
        if reason:
            stats["complete"] = False
        try:
            oracle = self.reconcile(directory, marker, stats["acknowledged"])
        except Exception as error:
            oracle = {"status": "UNKNOWN", "error": type(error).__name__}
        status = classify(stats, self.load, oracle)
        if reason == "OVERLOAD" and not stats["generator_limited"] and oracle.get("status") == "PASS" and not stats.get("all_phase_assertions", 0):
            status = "OVERLOAD"  # Incomplete latency remains explicit; this is not an SLO pass.
        elif reason in INVALID and status != "CORRECTNESS_FAILURE":
            status = reason
        if oracle.get("status") == "UNKNOWN" and status == "PASS":
            status = "INCOMPLETE"
        segments = []
        for i, step in enumerate(sequence or []):
            duration = (sequence[i + 1]["at"] if i + 1 < len(sequence) else seconds) - step["at"]
            reached = []
            for worker in range(workers):
                target = step["vu"] // workers + (worker < step["vu"] % workers)
                found = False
                history = directory / f"worker-{worker}-history.jsonl"
                if history.exists() and schedule:
                    with open(history, encoding="utf-8") as stream:
                        for line in stream:
                            sample = json.loads(line)
                            elapsed = sample["epoch"] - schedule["measure_start"]
                            if step["at"] <= elapsed < step["at"] + duration and sample["user_count"] == target:
                                found = True
                reached.append(found)
            segments.append({"at": step["at"], "vu": step["vu"],
                             "target_reached": all(reached),
                             "stats": aggregate(snapshots, duration, self.load, f"segment-{i}")})
        if segments and not all(s["target_reached"] for s in segments) and status != "CORRECTNESS_FAILURE":
            status = "GENERATOR_LIMITED"
        if not stats["complete"]:
            # A planned-duration denominator on an aborted run would fabricate throughput.
            for key in ("completed_rps", "successful_rps", "expected_rejection_rps", "start_rps"):
                stats[key] = None
        result = {"workload": workload, "vu": vu, "workers": workers, "label": label,
                  "warmup_seconds": warmup,
                  "status": status, "seconds": seconds, "wall_seconds": time.monotonic() - start,
                  "stats": stats, "oracle": oracle, "schedule": schedule, "directory": directory.name,
                  "stop_reason": reason, "profiled": profiled, "profiling": profiling,
                  "segments": segments,
                  "model": "closed-loop fixed think time; not independently offered arrival rate"}
        save(directory / "result.json", result)
        self.stages.append(result)
        save(self.rt.root / "stages.json", self.stages)
        print(workload, label, "VU", vu, status, "RPS", stats["completed_rps"], flush=True)
        return result

    @staticmethod
    def worker_files(directory, workers):
        snapshots = []
        for i in range(workers):
            path = directory / f"worker-{i}.json"
            if path.exists():
                try:
                    snapshots.append(json.loads(path.read_text()))
                except (ValueError, OSError):
                    pass
        return snapshots

    def search(self, workload):
        policy = Search(self.load["initial_vu"], self.load["growth"], self.load["relative_precision"],
                        self.load["overload_probes"], self.load["overload_factor"])
        started = time.monotonic()
        self.phase_deadline = started + self.load["discovery_budget_seconds"]
        vu = policy.next
        confirmations = []
        while vu is not None and time.monotonic() - started < self.load["discovery_budget_seconds"] and self.remaining() > 0:
            result = self.stage(workload, vu, label=policy.phase)
            if result["status"] == "GENERATOR_LIMITED" and result.get("workers", 1) < int(effective_cpus()["effective"]):
                result = self.stage(workload, vu, label="generator-recheck",
                                    worker_override=int(effective_cpus()["effective"]))
            vu = policy.observe(vu, result["status"])
            if result["status"] in ("SLO_BREACH", "OVERLOAD"):
                self.recovery_probe(workload)
            if result["status"] == "CORRECTNESS_FAILURE":
                break
        if policy.stopped is None:
            policy.stopped = "BUDGET_EXHAUSTED"
        deadline = started + self.load["workload_budget_seconds"]
        self.phase_deadline = deadline
        if policy.low is not None and policy.high is not None and policy.stopped in ("BRACKETED", "BUDGET_EXHAUSTED"):
            # Alternate order to expose drift instead of always running the failing level last.
            for repeat in range(self.load["confirm_repeats"]):
                for target in ((policy.low, policy.high) if repeat % 2 == 0 else (policy.high, policy.low)):
                    if time.monotonic() >= deadline:
                        break
                    result = self.stage(workload, target, self.load["confirm_seconds"], "confirm")
                    confirmations.append({"vu": target, "status": result["status"], "repeat": repeat})
                    if result["status"] in INVALID or result["status"] == "CORRECTNESS_FAILURE":
                        break
            stable_low = [c for c in confirmations if c["vu"] == policy.low]
            stable_high = [c for c in confirmations if c["vu"] == policy.high]
            confirmed = (len(stable_low) == self.load["confirm_repeats"] and all(c["status"] == "PASS" for c in stable_low)
                         and len(stable_high) == self.load["confirm_repeats"]
                         and all(c["status"] in ("SLO_BREACH", "OVERLOAD") for c in stable_high)
                         and not policy.contradictions)
        else:
            confirmed = False
        summary = {"low_observed": policy.low, "high_observed": policy.high, "confirmed": confirmed,
                   "stop_reason": policy.stopped, "history": policy.history, "confirmations": confirmations,
                   "non_monotonic_observations": policy.contradictions,
                   "capacity_authority": "colocated environment only"}
        self.searches[workload] = summary
        save(self.rt.root / "searches.json", self.searches)
        self.phase_deadline = None
        if policy.high and self.rt.config["runtime"]["enable_jfr_diagnostic"] and self.remaining() > 400:
            self.stage(workload, policy.high, 60, "diagnostic", profiled=True)
        return summary

    def recovery_probe(self, workload):
        """No restart/restore between overload and recovery observation."""
        import requests
        from .common import jwt
        start = time.monotonic()
        path = self.rt.root / "recovery.jsonl"
        samples = []
        healthy = 0
        collector = Collector(self.rt, self.rt.root / "recovery-metrics").start()
        try:
            while time.monotonic() - start < self.load["recovery_seconds"]:
                if self.rt.app.poll() is not None:
                    break
                before = time.monotonic()
                try:
                    token = jwt(self.fx.data["users"][0], self.rt.secret)
                    response = requests.get(self.rt.url + "/api/users/me", headers={"Authorization": "Bearer " + token}, timeout=(2, 3))
                    ms = (time.monotonic() - before) * 1000
                    ok = response.status_code == 200 and ms <= self.load["slo_read_p95_ms"]
                except requests.RequestException:
                    ms, ok = (time.monotonic() - before) * 1000, False
                samples.append({"elapsed": time.monotonic() - start, "ms": ms, "healthy": ok})
                healthy = healthy + 1 if ok else 0
                if healthy >= 5:
                    break
                time.sleep(1)
        finally:
            collector.stop()
        result = {"workload": workload, "status": "PASS" if healthy >= 5 else "FAIL",
                  "elapsed": time.monotonic() - start, "samples": samples,
                  "scope": "five consecutive authenticated probes; no restart; not a full queue-drain proof"}
        append(path, result)
        return result

    def endurance(self):
        candidates = [(name, search["low_observed"]) for name, search in self.searches.items() if search.get("confirmed")]
        if not candidates:
            save(self.rt.root / "endurance.json", {"status": "UNKNOWN", "reason": "No repeat-confirmed passing load; soak/spike cannot be anchored objectively"})
            return
        workload, low = next((pair for pair in candidates if pair[0] == "mixed"), candidates[0])
        # Restore before the sequence, never between its low/peak/recovery segments.
        base = max(1, int(low * 0.2))
        high = math.ceil(low * 2)
        spike_seconds = self.load["spike_seconds"]
        duration = 60 + spike_seconds + self.load["recovery_seconds"]
        spike = self.stage(workload, base, duration, "spike", sequence=[
            {"at": 0, "vu": base}, {"at": 60, "vu": high}, {"at": 60 + spike_seconds, "vu": base}])
        recovery = self.recovery_probe(workload)
        soak = self.stage(workload, max(1, int(low * 0.65)), self.load["soak_seconds"], "soak")
        save(self.rt.root / "endurance.json", {"spike": spike, "recovery": recovery, "soak": soak,
             "scope": "anchored to confirmed low, same immutable baseline"})
