import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "learning_market.py"
SPEC = importlib.util.spec_from_file_location("learning_market", MODULE_PATH)
learning_market = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(learning_market)


class LearningMarketTests(unittest.TestCase):
    def test_daily_summary_builds_ma5_without_lookahead(self):
        rows = [
            {"date": f"2026-09-0{index}", "open": index, "close": index, "high": index + 1,
             "low": index - 1, "amount": index * 100, "changePct": 1}
            for index in range(1, 7)
        ]

        summary = learning_market.daily_summary(rows, "2026-09-05")

        self.assertEqual(summary["ma5"], 3.0)
        self.assertEqual(summary["previousMa5"], 2.5)
        self.assertTrue(summary["ma5Rising"])

    def test_intraday_summary_stops_at_ten(self):
        rows = [
            {"time": "09:30", "open": 10, "high": 10.2, "low": 9.9, "close": 10.1},
            {"time": "09:45", "open": 10.1, "high": 10.5, "low": 10.0, "close": 10.4},
            {"time": "10:00", "open": 10.4, "high": 10.45, "low": 10.2, "close": 10.25},
            {"time": "10:05", "open": 10.25, "high": 11.0, "low": 10.2, "close": 10.9},
        ]

        summary = learning_market.intraday_summary(rows, 10, 9.8)

        self.assertEqual(summary["highBefore1000"], 10.5)
        self.assertEqual(summary["peakTime"], "09:45")
        self.assertEqual(summary["mfeBefore1000Pct"], 5.0)


if __name__ == "__main__":
    unittest.main()
