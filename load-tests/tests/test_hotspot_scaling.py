from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from run_hotspot_scaling import summarize


class HotspotSummaryTest(unittest.TestCase):
    def test_accounts_for_acknowledgements_and_expected_rejections(self):
        rows = [
            (201, None, 101, 10),
            (201, None, 102, 20),
            (409, "INSUFFICIENT_SEATS", None, 30),
            (503, "SERVICE_UNAVAILABLE", None, 40),
        ]
        report = summarize(rows, 2, 38, [101, 102])
        self.assertTrue(report["pass"])
        self.assertEqual(report["p95_ms"], 40)
        self.assertEqual(report["bookings_per_second"], 1)

    def test_fails_on_an_unacknowledged_booking_or_inconsistent_seats(self):
        rows = [(201, None, 101, 10)]
        self.assertFalse(summarize(rows, 1, 38, [101, 102])["pass"])
        self.assertFalse(summarize(rows, 1, 40, [101])["pass"])

    def test_fails_on_no_successes_or_on_an_unexpected_status(self):
        self.assertFalse(summarize([(503, "SERVICE_UNAVAILABLE", None, 10)], 1, 40, [])["pass"])
        rows = [(201, None, 101, 10), (409, "IDEMPOTENCY_CONFLICT", None, 20)]
        self.assertFalse(summarize(rows, 1, 39, [101])["pass"])
