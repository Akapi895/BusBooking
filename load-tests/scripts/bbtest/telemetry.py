"""Bounded metadata-only sampling. Queries do not retain SQL/credentials/payloads."""
from pathlib import Path
import subprocess
import threading
import time

import psutil

from .common import append, effective_cpus, cgroup_snapshot


class Collector:
    def __init__(self, rt, directory):
        self.rt, self.directory = rt, Path(directory)
        self.done = threading.Event()
        self.thread = None
        self.processes = {}

    def start(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        return self

    def run(self):
        tick = 0
        while not self.done.is_set():
            sample = {"epoch": time.time(), "system_cpu_pct": psutil.cpu_percent(),
                      "memory": psutil.virtual_memory()._asdict(), "cpu_allocation": effective_cpus(), "cgroup": cgroup_snapshot()}
            rows = []
            for parent, family in ((self.rt.app, "java"),):
                if parent and parent.poll() is None:
                    rows.append((parent.pid, family))
            try:
                root_pid = int((self.rt.pgdir / "data/postmaster.pid").read_text().splitlines()[0])
                postgres = psutil.Process(root_pid)
                rows.extend((p.pid, "postgres") for p in [postgres, *postgres.children(recursive=True)])
            except (psutil.Error, OSError, ValueError):
                pass
            sample["processes"] = []
            for pid, family in rows:
                try:
                    process = self.processes.setdefault(pid, psutil.Process(pid))
                    sample["processes"].append({"pid": pid, "family": family,
                        "cpu_one_core_pct": process.cpu_percent(), "rss": process.memory_info().rss,
                        "threads": process.num_threads(), "io": process.io_counters()._asdict()})
                except (psutil.Error, OSError):
                    pass
            if tick % 5 == 0:
                try:
                    with self.rt.connect() as conn:
                        conn.execute("SET statement_timeout='1000ms'")
                        sample["db_activity"] = conn.execute("SELECT state,wait_event_type,wait_event,count(*),"
                            "max(extract(epoch FROM now()-xact_start)) FROM pg_stat_activity "
                            "WHERE datname=current_database() AND application_name<>'acceptance_observer' "
                            "GROUP BY state,wait_event_type,wait_event").fetchall()
                        sample["db_totals"] = conn.execute("SELECT xact_commit,xact_rollback,blks_read,blks_hit,"
                            "tup_returned,tup_fetched,temp_bytes,deadlocks FROM pg_stat_database "
                            "WHERE datname=current_database()").fetchone()
                        sample["blocked_sessions"] = conn.execute("SELECT count(*) FROM pg_stat_activity "
                            "WHERE datname=current_database() AND cardinality(pg_blocking_pids(pid))>0").fetchone()[0]
                except Exception as error:
                    sample["db_unavailable"] = type(error).__name__
            append(self.directory / "resources.jsonl", sample)
            tick += 1
            self.done.wait(1)

    def stop(self):
        self.done.set()
        if self.thread:
            self.thread.join(timeout=10)


def diagnostic(rt, directory, seconds=60):
    """Separate replay only; never merge profiled throughput into capacity results."""
    directory = Path(directory)
    directory.mkdir(exist_ok=True, parents=True)
    outcomes = {}
    for name, arguments in (("threads", ["Thread.print", "-l"]),
                             ("heap", ["GC.heap_info"]),
                             ("jfr", ["JFR.start", "name=acceptance", "settings=profile",
                                      "jdk.InitialEnvironmentVariable#enabled=false",
                                      "jdk.InitialSystemProperty#enabled=false",
                                      "jdk.JVMInformation#enabled=false",
                                      f"duration={seconds}s", f"filename={directory / 'diagnostic.jfr'}"])):
        try:
            result = subprocess.run([str(rt.jdk / "bin/jcmd"), str(rt.app.pid), *arguments],
                                    capture_output=True, text=True, timeout=20)
            (directory / (name + ".txt")).write_text(result.stdout + result.stderr, encoding="utf-8")
            outcomes[name] = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            outcomes[name] = False
    return outcomes
