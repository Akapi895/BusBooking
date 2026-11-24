"""Exercise the real Locust hook/drain protocol against a local fake HTTP server.

This verifies the harness only, and makes no BusBooking performance claim.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from bbtest.common import save
from bbtest.runner import aggregate
import yaml


class Handler(BaseHTTPRequestHandler):
    forced_status = 200

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith("/api/locations"):
            data = [{"id": 1}]
        else:
            data = {"id": 1, "routeId": 1, "departureTime": "2030-01-01T00:00:00",
                    "status": "SCHEDULED", "availableSeats": 40}
            if self.path.split("?")[0] == "/api/trips":
                data = [data]
        body = json.dumps(data).encode()
        self.send_response(self.forced_status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class WorkerProcessTest(unittest.TestCase):
    def test_real_worker_ready_window_and_drained_failure_statistics(self):
        root = Path(os.environ.get("BB_VALIDATION_DIR", ROOT / ".validation"))
        root.mkdir(exist_ok=True)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for status in (200, 503):
                Handler.forced_status = status
                with tempfile.TemporaryDirectory(dir=root) as temp:
                    directory = Path(temp)
                    config = yaml.safe_load((ROOT / "config/acceptance.yaml").read_text())
                    load = dict(config["load"], think_min=0.01, think_max=0.02, drain_seconds=2,
                                connect_timeout=0.2, read_timeout=0.3)
                    fixture = {"users": [1, 2], "trips": [{"id": 1, "route": 1, "origin": 1, "destination": 2, "date": "2030-01-01"}],
                               "price": 150000, "capacity": 40}
                    save(directory / "fixture.json", fixture)
                    save(directory / "settings.json", {"fixture_path": str(directory / "fixture.json"), "load": load,
                        "directory": str(directory), "worker_index": 0, "workers": 1, "vu": 2,
                        "workload": "read", "seed": 1, "marker": "test"})
                    env = dict(os.environ, BB_SETTINGS=str(directory / "settings.json"), BB_JWT_SECRET="eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHg=",
                               PYTHONDONTWRITEBYTECODE="1")
                    with open(directory / "process.log", "w", encoding="utf-8") as log:
                        proc = subprocess.Popen([sys.executable, "-B", "-m", "locust", "-f", str(ROOT / "scripts/locust_workloads.py"),
                            "--headless", "--host", f"http://127.0.0.1:{server.server_port}", "-u", "2", "-r", "10", "--only-summary"],
                            env=env, stdout=log, stderr=log)
                        try:
                            end = time.monotonic() + 30
                            while not (directory / "ready-0.json").exists() and time.monotonic() < end and proc.poll() is None:
                                time.sleep(0.1)
                            self.assertTrue((directory / "ready-0.json").exists(), (directory / "process.log").read_text())
                            now = time.time()
                            save(directory / "schedule.json", {"measure_start": now + 1.2, "measure_end": now + 3.2})
                            proc.wait(timeout=20)
                        finally:
                            if proc.poll() is None:
                                proc.kill()
                                proc.wait()
                    worker = json.loads((directory / "worker-0.json").read_text())
                    result = aggregate([worker], 2, load)
                    self.assertTrue(result["complete"])
                    self.assertGreater(result["requests"], 0)
                    self.assertEqual(result["pending"], 0)
                    self.assertEqual(result["unexpected_errors"] == 0, status == 200)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
