import base64
from collections import Counter
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from bbtest.adaptive import Search, classify
from bbtest.common import jwt, validate_config, slot_permutation, slot_trip_index
from bbtest.contracts import ENDPOINTS, booking_valid, canonical, reset_code, verification_code
from bbtest.report import archive, build
from bbtest.runner import aggregate, Runner
from bbtest.common import save
from bbtest.contracts import REQUIRED_CASES
from package_kaggle import package

import yaml


class PolicyTest(unittest.TestCase):
    def test_no_400_or_2000_vu_ceiling(self):
        search = Search(initial=20)
        vu = 20
        while vu < 5000:
            vu = search.observe(vu, "PASS")
        self.assertGreaterEqual(vu, 5000)
        self.assertIsNone(search.high)

    def test_refines_and_probes_beyond_failure(self):
        search = Search(initial=1600, growth=1.25, precision=0.05, probes=2)
        self.assertEqual(search.observe(1600, "PASS"), 2000)
        self.assertEqual(search.observe(2000, "SLO_BREACH"), 1800)
        self.assertEqual(search.observe(1800, "PASS"), 1900)
        self.assertEqual(search.observe(1900, "PASS"), 1950)
        self.assertEqual(search.observe(1950, "SLO_BREACH"), 2145)
        self.assertEqual(search.observe(2145, "OVERLOAD"), 2360)
        self.assertIsNone(search.observe(2360, "OVERLOAD"))
        self.assertEqual((search.low, search.high, search.stopped), (1900, 1950, "BRACKETED"))

    def test_generator_limit_is_not_a_backend_failure_bound(self):
        search = Search()
        search.observe(20, "PASS")
        self.assertIsNone(search.observe(32, "GENERATOR_LIMITED"))
        self.assertIsNone(search.high)
        self.assertEqual(search.low, 20)

    def test_passing_overload_probe_invalidates_old_bracket(self):
        search = Search(initial=30, growth=1.1, precision=0.1)
        search.observe(30, "PASS")
        search.observe(33, "SLO_BREACH")
        next_vu = search.observe(37, "PASS")
        self.assertIsNone(search.high)
        self.assertGreater(next_vu, 37)
        self.assertTrue(search.contradictions)

    def test_no_passing_load_searches_down(self):
        search = Search(initial=20)
        self.assertEqual(search.observe(20, "SLO_BREACH"), 10)
        self.assertEqual(search.observe(10, "SLO_BREACH"), 5)
        self.assertEqual(search.observe(5, "PASS"), 7)


class MeasurementTest(unittest.TestCase):
    def setUp(self):
        self.config = validate_config(yaml.safe_load((ROOT / "config/acceptance.yaml").read_text()))
        self.load = self.config["load"]

    def worker(self, histogram, started=None, errors=0):
        count = sum(histogram.values())
        return {"complete": True, "lag_samples": 10, "lag_bad_samples": 0, "cpu_bad_samples": 0,
                "validity": {"measure": {"samples": 10, "lag_bad": 0, "cpu_bad": 0}},
                "phases": {"measure": {"started": count if started is None else started, "requests": count,
                    "unexpected_errors": errors, "completions_in_window": count,
                    "read": histogram, "write": {}, "status_codes": {"200": count}}}}

    def test_merge_histograms_not_average_worker_percentiles(self):
        result = aggregate([self.worker({"10": 990}), self.worker({"1000": 10})], 10, self.load)
        self.assertEqual(result["read_p95_ms"], 10)
        self.assertEqual(result["requests"], 1000)
        self.assertEqual(result["completed_rps"], 100)

    def test_pending_and_timeout_cannot_silently_pass(self):
        result = aggregate([self.worker({"10": 9}, started=10)], 10, self.load)
        self.assertEqual(classify(result, self.load), "INCOMPLETE")
        result = aggregate([self.worker({"10": 9, "15000": 1}, errors=1)], 10, self.load)
        self.assertEqual(classify(result, self.load), "SLO_BREACH")
        self.assertEqual(result["read_p95_ms"], 15000)

    def test_expected_business_rejections_are_distinct(self):
        worker = self.worker({"10": 100})
        worker["phases"]["measure"]["expected_rejections"] = 40
        result = aggregate([worker], 10, self.load)
        self.assertEqual(result["expected_rejections"], 40)
        self.assertEqual(classify(result, self.load), "PASS")
        result["assertions"] = 1
        self.assertEqual(classify(result, self.load), "CORRECTNESS_FAILURE")

    def test_invalid_timeouts_rejected(self):
        self.config["load"]["drain_seconds"] = 1
        with self.assertRaises(ValueError):
            validate_config(self.config)

    def test_generator_validity_not_diluted_by_warmup(self):
        worker = self.worker({"10": 100})
        worker.update(lag_samples=355, lag_bad_samples=10)
        worker["validity"]["measure"] = {"samples": 120, "lag_bad": 10, "cpu_bad": 0}
        result = aggregate([worker], 120, self.load)
        self.assertTrue(result["generator_limited"])

    def test_slow_rare_endpoint_cannot_hide_in_aggregate_p95(self):
        result = aggregate([self.worker({"10": 100})], 10, self.load)
        result["endpoints"] = {"GET /api/trips": {"p95_ms": 2000}}
        self.assertEqual(classify(result, self.load), "SLO_BREACH")


class ContractTest(unittest.TestCase):
    def test_distributed_write_slots_visit_all_trips_without_overbooking(self):
        for trips in (1, 5, 13, 200):
            capacity = 40
            permutation = slot_permutation(trips * capacity, 123)
            indexes = [slot_trip_index(i, trips, capacity, permutation) for i in range(trips * capacity)]
            self.assertEqual(Counter(indexes), {i: capacity for i in range(trips)})
            if trips > 1:
                self.assertGreater(len(set(indexes[:min(trips, 10)])), 1)
            with self.assertRaises(IndexError):
                slot_trip_index(trips * capacity, trips, capacity, permutation)

    def test_37_endpoints_and_canonical_ids(self):
        self.assertEqual(len(ENDPOINTS), 38)
        self.assertIn(("POST", canonical("/api/admin/bookings/7/refund")), ENDPOINTS)
        self.assertEqual(canonical("/api/admin/users/123/role?x=1"), "/api/admin/users/{id}/role")

    def test_actual_booking_dto_has_no_user_id(self):
        body = {"id": 1, "tripId": 2, "quantity": 3, "status": "HELD", "unitPrice": "0.10", "totalAmount": "0.30"}
        self.assertTrue(booking_valid(body, 99, 2, 3, "0.10"))
        body["totalAmount"] = "0.31"
        self.assertFalse(booking_valid(body, 99, 2, 3))

    def test_spread_reports_median_and_relative_deviation(self):
        from bbtest.runner import spread
        result = spread([90.0, 100.0, 110.0, None])
        self.assertEqual((result["n"], result["median"], result["min"], result["max"]), (3, 100.0, 90.0, 110.0))
        self.assertAlmostEqual(result["rsd_pct"], 10.0)
        self.assertIsNone(spread([5.0])["rsd_pct"])
        self.assertIsNone(spread([None]))

    def test_late_open_model_arrivals_breach_the_slo(self):
        from bbtest.adaptive import classify
        load = {"max_unexpected_error_ratio": 0.001, "slo_read_p95_ms": 300, "slo_write_p95_ms": 500}
        stats = {"complete": True, "requests": 1000, "started": 1000, "unexpected_errors": 0, "write_p95_ms": 50}
        self.assertEqual(classify(dict(stats, missed_arrivals=1), load), "PASS")
        self.assertEqual(classify(dict(stats, missed_arrivals=2), load), "SLO_BREACH")

    def test_reset_code_reads_only_the_reset_email(self):
        self.assertEqual(reset_code("Mã đặt lại mật khẩu của bạn: 654321\nMã có hiệu lực trong 10 phút"), "654321")
        self.assertIsNone(reset_code("Mã xác minh email của bạn: 012345"))

    def test_otp_ignores_six_digit_timestamp_fraction(self):
        self.assertEqual(verification_code("Mã xác minh email của bạn: 012345\nĐến 2026-11-15T12:00:00.123456Z (UTC)."), "012345")

    def test_fixture_jwt_matches_current_hs256_claim_contract(self):
        secret = base64.b64encode(b"x" * 32).decode()
        token = jwt(123, secret, now=1000)
        header, payload, signature = token.split(".")
        decode = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
        self.assertEqual(json.loads(decode(payload)), {"sub": "123", "iss": "busbooking", "iat": 1000, "exp": 87400})
        self.assertEqual(decode(signature), hmac.new(b"x" * 32, (header + "." + payload).encode(), hashlib.sha256).digest())

    def test_archives_exclude_private_dump_and_tools(self):
        validation = Path(os.environ.get("BB_VALIDATION_DIR", ROOT / ".validation"))
        validation.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=validation) as temp:
            root = Path(temp) / "run"
            root.mkdir()
            (root / "baseline.dump").write_bytes(b"not exportable")
            (root / "jdk").mkdir()
            (root / "jdk/tool.txt").write_text("private")
            build(root)
            self.assertEqual(json.loads((root / "summary.json").read_text())["capacity_status"], "UNCONFIRMED")
            path = archive(root)
            with zipfile.ZipFile(path) as bundle:
                self.assertIn("REPORT.md", bundle.namelist())
                self.assertFalse(any("jdk" in n or n.endswith(".dump") for n in bundle.namelist()))

    def test_partial_functional_inventory_is_not_a_pass(self):
        validation = Path(os.environ.get("BB_VALIDATION_DIR", ROOT / ".validation"))
        validation.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=validation) as temp:
            save(Path(temp) / "acceptance.json", [{"name": "functional.auth", "status": "PASS"}])
            summary = build(temp)
            self.assertNotEqual(summary["functional_status"], "PASS")
            self.assertIn("concurrency.last_seats", summary["missing_cases"])

    def test_interrupted_jsonl_still_exports_partial_evidence(self):
        validation = Path(os.environ.get("BB_VALIDATION_DIR", ROOT / ".validation"))
        validation.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=validation) as temp:
            run = Path(temp) / "run"
            run.mkdir()
            (run / "recovery.jsonl").write_text('{"status":"PASS"}\n{"status":', encoding="utf-8")
            result = build(run)
            self.assertEqual(result["invalid_recovery_rows"], [2])
            self.assertNotEqual(result["recovery_status"], "PASS")
            with zipfile.ZipFile(archive(run)) as bundle:
                self.assertIn("recovery.jsonl", bundle.namelist())
                self.assertIn("REPORT.md", bundle.namelist())

    def test_upload_kit_is_complete_and_digest_verified(self):
        validation = Path(os.environ.get("BB_VALIDATION_DIR", ROOT / ".validation"))
        validation.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=validation) as temp:
            path = package(ROOT, Path(temp) / "kit.zip")
            with zipfile.ZipFile(path) as bundle:
                names = bundle.namelist()
                manifest = json.loads(bundle.read("kit-manifest.json"))
                self.assertIn("load-tests/scripts/export_results.py", names)
                self.assertIn("load-tests/config/acceptance.yaml", names)
                self.assertIn("load-tests/notebook/busbooking-architecture-acceptance.ipynb", names)
                self.assertFalse(any(".validation/" in n or "/results/" in n for n in names))
                for name, sha in manifest.items():
                    self.assertEqual(hashlib.sha256(bundle.read(name)).hexdigest(), sha)

    def test_confirmation_orchestration_runs_all_repeats_without_a_shape_integer(self):
        validation = Path(os.environ.get("BB_VALIDATION_DIR", ROOT / ".validation"))
        validation.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=validation) as temp:
            config = yaml.safe_load((ROOT / "config/acceptance.yaml").read_text())
            config["runtime"]["enable_jfr_diagnostic"] = False
            class FakeRunner(Runner):
                def stage(inner, workload, vu, seconds=None, label="discovery", profiled=False, sequence=None, worker_override=None):
                    self.assertTrue(sequence is None or isinstance(sequence, list))
                    return {"status": "PASS" if vu <= 100 else "SLO_BREACH"}

                def recovery_probe(inner, workload):
                    return {"status": "PASS"}
            runner = FakeRunner(SimpleNamespace(config=config, root=Path(temp)), None, ROOT / "scripts")
            summary = runner.search("read")
            self.assertTrue(summary["confirmed"])
            self.assertEqual(len(summary["confirmations"]), 6)

    def test_failed_soak_blocks_overall_acceptance(self):
        validation = Path(os.environ.get("BB_VALIDATION_DIR", ROOT / ".validation"))
        validation.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=validation) as temp:
            root = Path(temp)
            config = yaml.safe_load((ROOT / "config/acceptance.yaml").read_text())
            save(root / "config.json", config)
            save(root / "acceptance.json", [{"name": name, "status": "PASS"} for name in REQUIRED_CASES])
            save(root / "architecture.json", {"status": "PASS"})
            save(root / "endpoint-coverage.json", {"status": "PASS", "covered": 32, "expected": 32})
            save(root / "searches.json", {name: {"confirmed": True, "stop_reason": "BRACKETED"} for name in config["workloads"]})
            save(root / "endurance.json", {"soak": {"status": "CORRECTNESS_FAILURE"}})
            result = build(root)
            self.assertEqual(result["capacity_status"], "CONFIRMED_COLOCATED_ONLY")
            self.assertNotEqual(result["endurance_status"], "PASS")
            self.assertNotEqual(result["overall_status"], "PASS_WITH_DECLARED_LIMITATIONS")


if __name__ == "__main__":
    unittest.main()
