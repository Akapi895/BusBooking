"""Evidence-backed hypotheses, never automatic causal or optimization claims."""
from pathlib import Path
from .common import read_journal


def inspect_stage(root, stage):
    path = Path(root) / "stages" / stage["directory"] / "resources.jsonl"
    schedule = stage.get("schedule") or {}
    observations = []
    samples, invalid = read_journal(path)
    for sample in samples:
        if schedule.get("measure_start", 0) <= sample.get("epoch", -1) < schedule.get("measure_end", 0):
            observations.append(sample)
    java, postgres, host, blocked, db_seen, rss, threads = [], [], [], 0, 0, [], []
    for sample in observations:
        allocation = sample["cpu_allocation"]["effective"] or 1
        processes = sample.get("processes", [])
        java.append(sum(p["cpu_one_core_pct"] for p in processes if p["family"] == "java") / (100 * allocation))
        postgres.append(sum(p["cpu_one_core_pct"] for p in processes if p["family"] == "postgres") / (100 * allocation))
        host.append(sample["system_cpu_pct"])
        rss.extend(p["rss"] for p in processes if p["family"] == "java")
        threads.extend(p["threads"] for p in processes if p["family"] == "java")
        if "blocked_sessions" in sample:
            db_seen += 1
            blocked += sample["blocked_sessions"] > 0
    mean = lambda values: sum(values) / len(values) if values else None
    stats = stage.get("stats", {})
    facts = {"samples": len(observations), "invalid_resource_rows": invalid,
             "db_samples": db_seen, "blocked_samples": blocked,
             "java_mean_allocated_cpu_fraction": mean(java), "postgres_mean_allocated_cpu_fraction": mean(postgres),
             "host_mean_cpu_pct": mean(host), "java_peak_rss_bytes": max(rss) if rss else None,
             "java_peak_threads": max(threads) if threads else None,
             "mean_response_bytes": stats.get("bytes", 0) / max(1, stats.get("requests", 0)),
             "generator_limited": stats.get("generator_limited"), "trial_status": stage["status"]}
    hypotheses = []
    if blocked:
        hypotheses.append("DB_LOCK_CONTENTION_OBSERVED")
    if java and mean(java) >= 0.75:
        hypotheses.append("JAVA_CPU_PRESSURE")
    if postgres and mean(postgres) >= 0.75:
        hypotheses.append("POSTGRES_CPU_PRESSURE")
    if host and mean(host) >= 90:
        hypotheses.append("SHARED_HOST_CPU_PRESSURE")
    if stats.get("generator_limited"):
        hypotheses.append("LOAD_GENERATOR_LIMITED_BACKEND_CAPACITY_UNKNOWN")
    if facts["mean_response_bytes"] >= 1024 * 1024:
        hypotheses.append("LARGE_RESPONSE_WORKLOAD")
    return {"directory": stage["directory"], "workload": stage["workload"], "vu": stage["vu"],
            "facts": facts, "hypotheses": hypotheses, "source": str(path.relative_to(root)),
            "authority": "observed metrics + analyst thresholds, not causal proof",
            "unknowns": ["Hikari occupancy not directly exposed", "Inspect separate JFR for GC/CPU attribution",
                         "No backend-only capacity claim on a colocated host"]}
