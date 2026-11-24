import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from bbtest.common import save
from bbtest.configuration import select
from bbtest.report import archive, build
from bbtest.smoke import run


class SmokeTest(unittest.TestCase):
    def test_profile_resolves_to_minimal_flow_without_affecting_acceptance(self):
        smoke = select(ROOT / "config", "smoke")
        full = select(ROOT / "config", "acceptance")
        self.assertEqual(smoke["profile"], "smoke")
        self.assertEqual(smoke["load"]["initial_vu"], 1)
        self.assertEqual(smoke["fixture"]["users"], 5)
        self.assertFalse(smoke["runtime"]["enable_faults"])
        self.assertEqual(full["profile"], "acceptance")
        self.assertEqual(full["concurrency"]["rounds"], 100)

    def test_smoke_uses_two_cases_then_three_single_vu_trials(self):
        validation = Path(os.environ.get("BB_VALIDATION_DIR", ROOT / ".validation"))
        validation.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=validation) as temp:
            config = select(ROOT / "config", "smoke")
            rt = SimpleNamespace(root=Path(temp), config=config)
            with patch("bbtest.smoke.Acceptance") as api, patch("bbtest.smoke.Runner") as runner:
                api.return_value.case.return_value = {"name": "case", "status": "PASS"}
                runner.return_value.stage.side_effect = lambda workload, *args, **kwargs: {"workload": workload, "status": "PASS"}
                result = run(rt, None, ROOT / "scripts")
                self.assertEqual(result["status"], "PASS")
                self.assertEqual(api.return_value.case.call_count, 2)
                self.assertEqual(runner.return_value.stage.call_count, 3)
                for call in runner.return_value.stage.call_args_list:
                    self.assertEqual(call.args[1], 1)
                    self.assertEqual(call.kwargs["worker_override"], 1)
                runner.return_value.search.assert_not_called()
                runner.return_value.endurance.assert_not_called()

    def test_smoke_report_does_not_claim_full_acceptance_and_requires_complete_trials(self):
        validation = Path(os.environ.get("BB_VALIDATION_DIR", ROOT / ".validation"))
        validation.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=validation) as temp:
            root = Path(temp)
            save(root / "config.json", select(ROOT / "config", "smoke"))
            save(root / "architecture.json", {"status": "PASS"})
            save(root / "acceptance.json", [{"name": name, "status": "PASS"}
                for name in ("functional.auth", "functional.catalog_and_booking")])
            save(root / "smoke.json", {"status": "PASS"})
            stages = [{"workload": name, "vu": 1, "label": "smoke", "status": "PASS", "stats": {"complete": True}}
                      for name in ("read", "write", "mixed")]
            save(root / "stages.json", stages)
            result = build(root)
            self.assertEqual(result["overall_status"], "SMOKE_PASS")
            self.assertFalse(result["full_acceptance_profile"])
            self.assertEqual(result["capacity_status"], "NOT_MEASURED")
            self.assertEqual(result["endurance_status"], "NOT_REQUESTED")
            stages[-1]["stats"]["complete"] = False
            save(root / "stages.json", stages)
            self.assertNotEqual(build(root)["overall_status"], "SMOKE_PASS")
            self.assertTrue(archive(root).is_file())


if __name__ == "__main__":
    unittest.main()
