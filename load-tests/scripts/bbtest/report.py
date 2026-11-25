"""Report only supported claims; preserve failed/incomplete trials in every export."""
import csv
import json
from pathlib import Path
import zipfile

from .common import save, read_journal
from .contracts import ENDPOINTS, REQUIRED_CASES
from .adaptive import classify
from .bottlenecks import inspect_stage


def build(root):
    root = Path(root)
    def read(name, default):
        path = root / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    cases = read("acceptance.json", [])
    searches = read("searches.json", {})
    stages = read("stages.json", [])
    architecture = read("architecture.json", {"status": "UNKNOWN"})
    coverage = read("endpoint-coverage.json", {"status": "UNKNOWN"})
    fatal = read("fatal.json", None)
    endurance = read("endurance.json", {"status": "UNKNOWN"})
    open_model = read("open-model.json", {"status": "UNKNOWN"})
    missing_cases = sorted(REQUIRED_CASES - {c["name"] for c in cases})
    functional_ok = not missing_cases and all(c["status"] == "PASS" for c in cases)
    capacity_ok = bool(searches) and all(s.get("confirmed") for s in searches.values())
    config = read("config.json", {})
    expected_workloads = config.get("workloads", [])
    capacity_ok = capacity_ok and set(expected_workloads) == set(searches)
    recovery_path = root / "recovery.jsonl"
    recoveries, invalid_recovery = read_journal(recovery_path)
    endurance_ok = False
    spike = endurance.get("spike", {})
    segments = spike.get("segments", [])
    if len(segments) == 3 and config.get("load"):
        endurance_ok = (all(s.get("target_reached") for s in segments)
            and spike.get("oracle", {}).get("status") == "PASS"
            and not spike.get("stats", {}).get("assertions", 0)
            and not spike.get("stats", {}).get("generator_limited", True)
            and classify(segments[0]["stats"], config["load"]) == "PASS"
            and classify(segments[2]["stats"], config["load"]) == "PASS"
            and endurance.get("recovery", {}).get("status") == "PASS"
            and endurance.get("soak", {}).get("status") == "PASS")
    recovery_ok = bool(recoveries) and not invalid_recovery and all(r["status"] == "PASS" for r in recoveries)
    full_profile = (config.get("profile") == "acceptance" and config.get("concurrency", {}).get("rounds", 0) >= 100
                    and set(expected_workloads) == {"read", "write", "mixed", "hotspot"}
                    and config.get("load", {}).get("confirm_repeats", 0) >= 3)
    cleanup = read("cleanup.json", {"status": "PASS"})
    overall_ok = (functional_ok and capacity_ok and endurance_ok and recovery_ok and full_profile
                  and architecture["status"] == "PASS" and coverage["status"] == "PASS" and not fatal
                  and cleanup["status"] == "PASS")
    smoke = read("smoke.json", {})
    smoke_mode = config.get("profile") == "smoke"
    smoke_ok = (smoke_mode and smoke.get("status") == "PASS" and not fatal and cleanup["status"] == "PASS"
                and architecture["status"] == "PASS"
                and {c["name"] for c in cases} == {"functional.auth", "functional.catalog_and_booking"}
                and all(c["status"] == "PASS" for c in cases)
                and len(stages) == 4 and {s["workload"] for s in stages} == {"read", "write", "mixed", "open-write"}
                and all(s["status"] == "PASS" and s.get("stats", {}).get("complete") for s in stages))
    overall = "SMOKE_PASS" if smoke_ok else ("PASS_WITH_DECLARED_LIMITATIONS" if overall_ok else "FAIL_OR_INCOMPLETE")
    evidence = {"functional_status": "SMOKE_ONLY" if smoke_mode else ("PASS" if functional_ok else "FAIL_OR_INCOMPLETE"),
                "missing_cases": missing_cases,
                "overall_status": overall, "mode": config.get("profile"),
                "smoke_status": "PASS" if smoke_ok else ("FAIL_OR_INCOMPLETE" if smoke_mode else "NOT_REQUESTED"),
                "full_acceptance_profile": full_profile,
                "endurance_status": "NOT_REQUESTED" if smoke_mode else ("PASS" if endurance_ok else "FAIL_OR_INCOMPLETE"),
                "recovery_status": "NOT_REQUESTED" if smoke_mode else ("PASS" if recovery_ok else "FAIL_OR_INCOMPLETE"),
                "invalid_recovery_rows": invalid_recovery, "cleanup_status": cleanup["status"],
                "architecture_status": architecture["status"], "endpoint_coverage": coverage,
                "capacity_status": "NOT_MEASURED" if smoke_mode else ("CONFIRMED_COLOCATED_ONLY" if capacity_ok else "UNCONFIRMED"),
                "fatal": fatal, "searches": searches, "open_model": open_model,
                "known_gaps": ["One host: CPUs are split between backend and generator, but memory, disk and caches stay shared",
                    "Capacity search uses the closed-loop VU model; only the write open-model trials control the arrival rate",
                    "Pool occupancy unavailable unless independently exposed; no guessed pool size",
                    "JAR boundary scan does not prove every architectural property"]}
    save(root / "summary.json", evidence)
    bottlenecks = [inspect_stage(root, stage) for stage in stages if stage.get("directory")]
    save(root / "bottlenecks.json", bottlenecks)
    with open(root / "stage-summary.csv", "w", newline="", encoding="utf-8") as stream:
        fields = ["workload", "label", "vu", "status", "rps", "read_p95_ms", "write_p95_ms", "errors", "profiled"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for stage in stages:
            stats = stage.get("stats", {})
            writer.writerow({"workload": stage["workload"], "label": stage["label"], "vu": stage["vu"], "status": stage["status"],
                "rps": stats.get("completed_rps"), "read_p95_ms": stats.get("read_p95_ms"), "write_p95_ms": stats.get("write_p95_ms"),
                "errors": stats.get("unexpected_errors"), "profiled": stage.get("profiled", False)})
    lines = ["# BusBooking architecture acceptance", "", "## Authority", "",
             "Unchanged uploaded JAR; external test fixtures and fault schedules. All timings are environment/workload specific.",
             "No pass is inferred from a missing trial. Profiled replays are excluded from capacity bounds.", "",
             "## Functional, concurrency and failure contracts", "", "| Case | Result | Seconds |", "|---|---|---:|"]
    if smoke_mode:
        lines[0] = "# BusBooking — sequential smoke check"
        lines[4:4] = ["**Smoke only:** checks startup, auth/business flow, one-VU load, data oracle and output export.",
                       "Full architecture/capacity/concurrency/fault/endurance acceptance was not requested.", ""]
    lines.extend(f"| {c['name']} | {c['status']} | {c.get('seconds', 0):.2f} |" for c in cases)
    lines += ["", f"Endpoint surface: {coverage.get('covered', 0)}/{coverage.get('expected', len(ENDPOINTS))} positive method/path observations.",
              f"JAR boundary check: {architecture['status']}.", "", "## Capacity brackets", "",
              "| Workload | Observed passing VU | Observed failing VU | Repeat-confirmed | Search stop |", "|---|---:|---:|---|---|"]
    for name, result in searches.items():
        lines.append(f"| {name} | {result.get('low_observed')} | {result.get('high_observed')} | {result.get('confirmed')} | {result['stop_reason']} |")
    lines += ["", "## Repeat variability", "",
              "Median and relative standard deviation (RSD) across confirmation repeats. RSD above "
              f"{config.get('load', {}).get('max_rsd_pct', '?')}% marks the level unstable.", "",
              "| Workload | VU | Successful RPS median | RPS RSD % | Read p95 median | Write p95 median | Stable |",
              "|---|---:|---:|---:|---:|---:|---|"]
    for name, result in searches.items():
        for level, metrics in (result.get("variability") or {}).items():
            def cell(metric, key):
                value = (metrics.get(metric) or {}).get(key)
                return "-" if value is None else f"{value:.1f}"
            stable = result.get("stable") if str(result.get("low_observed")) == level else ""
            lines.append(f"| {name} | {level} | {cell('successful_rps', 'median')} | {cell('successful_rps', 'rsd_pct')} | "
                         f"{cell('read_p95_ms', 'median')} | {cell('write_p95_ms', 'median')} | {stable} |")
    lines += ["", "## Open model (fixed arrival rate, booking)", ""]
    if open_model.get("levels"):
        lines += [f"Rates are fractions of the confirmed closed-loop write throughput "
                  f"({open_model['base_closed_successful_rps']:.1f} req/s). {open_model['scope']}.", "",
                  "| Fraction | Target req/s | Offered req/s | Successful req/s | p95 ms | p99 ms | Late arrivals | Result |",
                  "|---:|---:|---:|---:|---:|---:|---:|---|"]
        for level in open_model["levels"]:
            values = [level.get(k) for k in ("offered_rps", "successful_rps", "write_p95_ms", "write_p99_ms")]
            text = ["-" if v is None else f"{v:.1f}" for v in values]
            lines.append(f"| {level['fraction']:g} | {level['target_rps']:.1f} | {' | '.join(text)} | "
                         f"{level.get('missed_arrivals')} | {level['status']} |")
    else:
        lines.append(f"Not measured: {open_model.get('reason', 'no open-model trials ran')}.")
    lines += ["", "## Interpreting bottlenecks", "",
              "Inspect each stage's resources.jsonl, worker history, latency histograms and separate diagnostic replay.",
              "DB Lock waits + blocked sessions support a contention hypothesis; Java CPU/JFR support a CPU/GC hypothesis.",
              "Neither CPU correlation nor increasing latency alone establishes causality.",
              "No global CPU percentage is inferred from one-core process CPU%. Quota/affinity are recorded separately.",
              "", "| Trial | Metric-backed hypotheses (not causal proof) |", "|---|---|"]
    lines.extend(f"| {item['directory']} | {', '.join(item['hypotheses']) or 'No supported attribution; inspect traces'} |" for item in bottlenecks)
    lines += [
              "", "## Endurance", "", f"Status: {evidence['endurance_status']}; recovery: {evidence['recovery_status']}.",
              "", f"Overall: **{evidence['overall_status']}** (declared topology/idempotency limitations still apply).",
              "", "## Residual limitations", ""]
    lines.extend("- " + item for item in evidence["known_gaps"])
    if fatal:
        lines += ["", "## Run interrupted", "", json.dumps(fatal)]
    (root / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Standalone SVG charts, no matplotlib dependency or hidden notebook state.
    chart = ["<svg xmlns='http://www.w3.org/2000/svg' width='960' height='500' viewBox='0 0 960 500'>",
             "<rect width='960' height='500' fill='white'/><text x='30' y='30'>Observed completed RPS by VU (unprofiled trials)</text>"]
    usable = [s for s in stages if s.get("stats", {}).get("complete") and not s.get("profiled")
              and s["stats"].get("completed_rps") is not None]
    max_vu = max([s["vu"] for s in usable] + [1])
    max_rps = max([s["stats"]["completed_rps"] for s in usable] + [1])
    colors = {"read": "#2563eb", "write": "#dc2626", "mixed": "#059669", "hotspot": "#9333ea"}
    for stage in usable:
        x = 60 + stage["vu"] / max_vu * 830
        y = 430 - stage["stats"]["completed_rps"] / max_rps * 360
        chart.append(f"<circle cx='{x:.2f}' cy='{y:.2f}' r='4' fill='{colors[stage['workload']]}'><title>{stage['workload']} {stage['vu']} VU {stage['status']}</title></circle>")
    chart += [f"<text x='60' y='470'>0 VU</text><text x='800' y='470'>{max_vu} VU</text>", "</svg>"]
    (root / "throughput.svg").write_text("\n".join(chart), encoding="utf-8")
    return evidence


def archive(root):
    root = Path(root)
    target = root.parent / (root.name + ".zip")
    # Explicit evidence allowlist: never archive the DB dump, private state, tools or package caches.
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            if not path.is_file() or relative.parts[0] in {"jdk", "private"} or path.suffix == ".dump":
                continue
            if path.suffix in {".json", ".jsonl", ".csv", ".log", ".md", ".svg", ".jfr", ".txt", ".yaml", ".py"}:
                bundle.write(path, str(relative))
    return target
