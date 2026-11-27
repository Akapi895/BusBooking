"""Run soak_locust.py against a running Compose cluster, then reconcile seats and pull Prometheus metrics.

Example (3 backends; see load-tests/README.md for bringing the cluster up):
  python run_soak.py --dsn postgresql://busbooking_user:PW@127.0.0.1:5435/busbooking_dev_fresh \
      --jwt-secret "$JWT_SECRET" --label 3-backends --minutes 30 --out ../results/soak/3-backends
"""
import argparse
import csv
import datetime
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

import psycopg

HERE = Path(__file__).resolve().parent
VIETNAM = datetime.timezone(datetime.timedelta(hours=7))
API = 'uri!~"/actuator.*"'
QUERIES = {  # name -> PromQL, evaluated over the run window
    "requests_per_second": f'sum(rate(http_server_requests_seconds_count{{{API}}}[1m]))',
    "requests_per_second_by_instance": f'sum by (instance) (rate(http_server_requests_seconds_count{{{API}}}[1m]))',
    "server_errors_per_second": f'sum(rate(http_server_requests_seconds_count{{{API},status=~"5..",status!="503"}}[1m])) or vector(0)',
    "p95_seconds_by_endpoint": f'histogram_quantile(0.95, sum by (le, method, uri) (rate(http_server_requests_seconds_bucket{{{API}}}[1m])))',
    "p99_seconds_by_endpoint": f'histogram_quantile(0.99, sum by (le, method, uri) (rate(http_server_requests_seconds_bucket{{{API}}}[1m])))',
    "hikari_pending": "sum(hikaricp_connections_pending)",
    "hikari_active": "sum(hikaricp_connections_active)",
    "pg_lock_waits": "pg_lock_waits_waiting",
    "heap_bytes_by_instance": 'sum by (instance) (jvm_memory_used_bytes{area="heap"})',
}


def snapshot(conn):
    """Accounts to load with, routes that have trips, and every trip's free seats before the run."""
    users = [r[0] for r in conn.execute(
        "SELECT u.id FROM users u JOIN roles r ON r.id = u.role_id "
        "WHERE r.name = 'USER' AND u.email_verified AND u.status = 'ACTIVE' ORDER BY u.id")]
    routes = [list(r) for r in conn.execute(
        "SELECT DISTINCT r.origin_id, r.destination_id FROM routes r JOIN trips t ON t.route_id = r.id "
        "WHERE t.status = 'SCHEDULED' AND t.departure_time > now() AT TIME ZONE 'Asia/Ho_Chi_Minh' ORDER BY 1, 2")]
    seats = dict(conn.execute("SELECT id, available_seats FROM trips").fetchall())
    last_booking = conn.execute("SELECT coalesce(max(id), 0) FROM bookings").fetchone()[0]
    return users, routes, seats, last_booking


def reconcile(conn, seats_before, last_booking):
    """Every trip lost exactly the seats of the run's bookings that still hold them."""
    taken = dict(conn.execute(
        "SELECT trip_id, sum(quantity) FROM bookings WHERE id > %s AND status IN ('HELD', 'CONFIRMED') "
        "GROUP BY trip_id", (last_booking,)).fetchall())
    seats_after = dict(conn.execute("SELECT id, available_seats FROM trips").fetchall())
    seat_mismatches = [trip for trip, before in seats_before.items()
                       if before - seats_after[trip] != taken.get(trip, 0)]
    statuses = dict(conn.execute(
        "SELECT status, count(*) FROM bookings WHERE id > %s GROUP BY status", (last_booking,)).fetchall())
    # The expiry job runs every 15 s on each instance; a hold a minute past its deadline means it is not running.
    stale_holds = conn.execute(
        "SELECT count(*) FROM bookings WHERE status = 'HELD' "
        "AND hold_expires_at < now() AT TIME ZONE 'Asia/Ho_Chi_Minh' - interval '1 minute'").fetchone()[0]
    bad_money = conn.execute(
        "SELECT count(*) FROM bookings WHERE id > %s AND total_amount <> unit_price * quantity",
        (last_booking,)).fetchone()[0]
    return {"seat_mismatches": len(seat_mismatches), "seat_mismatch_examples": seat_mismatches[:10],
            "stale_holds": stale_holds, "money_mismatches": bad_money, "booking_statuses": statuses,
            "status": "PASS" if not (seat_mismatches or stale_holds or bad_money) else "FAIL"}


def prometheus(base, start, end):
    out = {}
    for name, query in QUERIES.items():
        url = f"{base}/api/v1/query_range?" + urllib.parse.urlencode(
            {"query": query, "start": start, "end": end, "step": "30s"})
        out[name] = json.loads(urllib.request.urlopen(url, timeout=30).read())["data"]["result"]
    return out


def series_stats(result):
    """Per series: first, last, max and mean of the sampled values (NaN samples skipped)."""
    stats = {}
    for series in result:
        values = [float(v) for _, v in series["values"] if v not in ("NaN", "+Inf")]
        if values:
            label = " ".join(f"{k}={v}" for k, v in sorted(series["metric"].items())) or "total"
            stats[label] = {"first": values[0], "last": values[-1], "max": max(values), "mean": sum(values) / len(values)}
    return stats


def locust_summary(prefix):
    rows = list(csv.DictReader(open(f"{prefix}_stats.csv", encoding="utf-8")))
    pick = ("Request Count", "Failure Count", "Requests/s", "50%", "95%", "99%", "Max Response Time")
    return {row["Name"]: {k: float(row[k]) for k in pick} for row in rows}


def drift(prefix, minutes=5):
    """Aggregated p95 over the first and last few minutes of the steady part, from Locust's history."""
    rows = [r for r in csv.DictReader(open(f"{prefix}_stats_history.csv", encoding="utf-8"))
            if r["Name"] == "Aggregated" and r["95%"] not in ("N/A", "0")]
    if not rows:
        return {}
    start, end = int(rows[0]["Timestamp"]), int(rows[-1]["Timestamp"])
    first = [float(r["95%"]) for r in rows if start + 60 <= int(r["Timestamp"]) < start + 60 + minutes * 60]
    last = [float(r["95%"]) for r in rows if int(r["Timestamp"]) >= end - minutes * 60]
    mean = lambda xs: round(sum(xs) / len(xs), 1) if xs else None
    return {"p95_ms_first_minutes": mean(first), "p95_ms_last_minutes": mean(last), "window_minutes": minutes}


def statuses(directory):
    total = {}
    for path in directory.glob("statuses-*.json"):
        for key, count in json.loads(path.read_text(encoding="utf-8")).items():
            total[key] = total.get(key, 0) + count
    return dict(sorted(total.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--jwt-secret", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--host", default="http://127.0.0.1:5173")
    parser.add_argument("--prometheus", default="http://127.0.0.1:9090")
    parser.add_argument("--minutes", type=float, default=30)
    parser.add_argument("--users", type=int, default=200)
    parser.add_argument("--spawn-rate", type=float, default=10)
    # One Locust process tops out near 700 req/s on a desktop CPU; workers spread the generator over cores.
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--think-min", type=float, default=0.2)
    parser.add_argument("--think-max", type=float, default=0.8)
    parser.add_argument("--abandon-ratio", type=float, default=0.15)
    parser.add_argument("--cancel-ratio", type=float, default=0.10)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    with psycopg.connect(args.dsn, autocommit=True) as conn:
        users, routes, seats_before, last_booking = snapshot(conn)
    settings = {"user_ids": users, "routes": routes, "jwt_secret": args.jwt_secret,
                "today": datetime.datetime.now(VIETNAM).date().isoformat(),
                "think_min": args.think_min, "think_max": args.think_max,
                "abandon_ratio": args.abandon_ratio, "cancel_ratio": args.cancel_ratio,
                "status_dir": str(args.out)}
    # Holds the JWT secret, so it lives in a temp file that is removed after the run, never next to the results.
    handle, name = tempfile.mkstemp(suffix=".json")
    os.close(handle)
    settings_path = Path(name)
    settings_path.write_text(json.dumps(settings), encoding="utf-8")

    for old in args.out.glob("statuses-*.json"):
        old.unlink()
    env = {**os.environ, "BB_SOAK": str(settings_path), "PYTHONPATH": str(HERE)}
    locust = [sys.executable, "-m", "locust", "-f", str(HERE / "soak_locust.py")]
    workers = [subprocess.Popen(locust + ["--worker", "--master-host", "127.0.0.1"], env=env)
               for _ in range(args.workers)]
    started = time.time()
    subprocess.run(locust + ["--headless", "--master", "--expect-workers", str(args.workers),
                             "-u", str(args.users), "-r", str(args.spawn_rate), "-t", f"{int(args.minutes * 60)}s",
                             "--host", args.host, "--csv", str(args.out / "locust"), "--csv-full-history",
                             "--only-summary", "--stop-timeout", "10"], env=env, check=False)
    ended = time.time()
    for worker in workers:
        worker.wait(timeout=60)
    settings_path.unlink()
    time.sleep(20)  # let a last expiry pass run before reconciling

    with psycopg.connect(args.dsn, autocommit=True) as conn:
        oracle = reconcile(conn, seats_before, last_booking)
    metrics = prometheus(args.prometheus, started, ended)
    (args.out / "prometheus.json").write_text(json.dumps(metrics), encoding="utf-8")
    summary = {"label": args.label, "started_utc": datetime.datetime.fromtimestamp(started, datetime.timezone.utc).isoformat(),
               "duration_minutes": round((ended - started) / 60, 1),
               "load": {"users": args.users, "spawn_rate": args.spawn_rate, "think_seconds": [args.think_min, args.think_max],
                        "abandon_ratio": args.abandon_ratio, "cancel_ratio": args.cancel_ratio},
               "locust": locust_summary(args.out / "locust"), "p95_drift": drift(args.out / "locust"),
               "statuses": statuses(args.out),
               "oracle": oracle, "prometheus": {name: series_stats(result) for name, result in metrics.items()
                                                if name != "p95_seconds_by_endpoint" and name != "p99_seconds_by_endpoint"}}
    for quantile in ("p95", "p99"):
        summary["prometheus"][f"{quantile}_seconds_by_endpoint"] = series_stats(metrics[f"{quantile}_seconds_by_endpoint"])
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"label": args.label, "oracle": oracle, "aggregated": summary["locust"].get("Aggregated"),
                      "p95_drift": summary["p95_drift"]}, indent=2, ensure_ascii=False))
    return 0 if oracle["status"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
