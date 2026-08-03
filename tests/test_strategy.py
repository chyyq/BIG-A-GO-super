import importlib.util
import unittest
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("update_data", ROOT / "scripts" / "update_data.py")
STRATEGY = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(STRATEGY)


def tail_quote(**overrides):
    quote = {
        "code": "000001",
        "name": "测试股份",
        "market": "SZ",
        "price": 10.60,
        "pct": 6.0,
        "amount": 420_000_000,
        "turnover": 12.0,
        "volumeRatio": 1.8,
        "high": 10.65,
        "low": 10.00,
        "open": 10.10,
        "preClose": 10.00,
        "avgPrice": 10.30,
        "amplitude": 6.5,
        "mainNet": 28_000_000,
        "superNet": 12_000_000,
        "floatMarketCap": 12_000_000_000,
        "industry": "测试行业",
        "boardFrontPct": 0.10,
        "dailyMetrics": {
            "historyAvailable": True,
            "amountRatio": 1.55,
            "ma5Rising": True,
            "deviationMA5Pct": 8.0,
            "gain5dPct": 12.0,
            "gain10dPct": 20.0,
            "prevDayReturn": 1.2,
            "closeAboveBreakout": True,
            "firstPullbackProxy": False,
            "surgeCount5d": 1,
        },
    }
    quote.update(overrides)
    return quote


def strong_board():
    return {
        "code": "BK0001",
        "name": "测试行业",
        "rank": 4,
        "passed": 5,
        "qualified": True,
        "score": 92,
        "criteria": ["continuity", "amount", "ladder", "leader", "tail rank"],
        "limitUpCount": 2,
        "bigUpCount": 6,
    }


class StrategyV31Tests(unittest.TestCase):
    def test_mid_trend_tail_candidate_passes(self):
        item = STRATEGY.evaluate_stock_snapshot(
            tail_quote(),
            strong_board(),
            {STRATEGY.STRATEGY_TAIL_MAIN},
            datetime(2026, 7, 16, 14, 20, tzinfo=STRATEGY.CN_TZ),
            {"emotionScore": 82, "riskLevel": "NORMAL", "marketGatePassed": True},
        )
        self.assertIsNotNone(item)
        self.assertEqual(item["strategyId"], "TAIL_T1_V31_EMPIRICAL")
        self.assertIn(item["candidateStatus"], {"STRONG_CANDIDATE", "NORMAL_CANDIDATE"})
        self.assertEqual(item["signalType"], "T3_TREND_BREAKOUT")

    def test_high_crowding_fishtail_is_rejected(self):
        quote = tail_quote(amplitude=11.2, turnover=28.0)
        quote["dailyMetrics"] = {
            **quote["dailyMetrics"],
            "amountRatio": 2.6,
            "gain5dPct": 31.0,
            "gain10dPct": 46.0,
            "surgeCount5d": 3,
        }
        item = STRATEGY.evaluate_stock_snapshot(
            quote,
            strong_board(),
            {STRATEGY.STRATEGY_TAIL_MAIN},
            datetime(2026, 7, 16, 14, 20, tzinfo=STRATEGY.CN_TZ),
            {"emotionScore": 82, "riskLevel": "NORMAL", "marketGatePassed": True},
        )
        self.assertIsNone(item)

    def test_one_day_rebound_without_prior_trend_is_rejected(self):
        quote = tail_quote(pct=6.2, amplitude=7.8)
        quote["dailyMetrics"] = {
            **quote["dailyMetrics"],
            "historyAvailable": True,
            "priorMA5Rising": False,
            "previousCloseAboveMA5": False,
            "ma5AboveMA10": True,
        }
        item = STRATEGY.evaluate_stock_snapshot(
            quote,
            strong_board(),
            {STRATEGY.STRATEGY_TAIL_MAIN},
            datetime(2026, 7, 16, 14, 20, tzinfo=STRATEGY.CN_TZ),
            {"emotionScore": 82, "riskLevel": "NORMAL", "marketGatePassed": True},
        )
        self.assertIsNone(item)

    def test_next_day_plan_waits_for_opening_confirmation(self):
        plan = STRATEGY.next_day_plan("PLAN_S")
        self.assertEqual(plan["auctionWatchTime"], "09:25-09:30")
        self.assertEqual(plan["firstNodeTime"], "09:30-09:35")
        self.assertTrue(plan["openingOverride"])

    def test_0932_uses_intraday_accumulation_thresholds(self):
        now = datetime(2026, 7, 16, 9, 32, tzinfo=STRATEGY.CN_TZ)
        quote = {
            "code": "000002",
            "name": "早盘测试",
            "market": "SZ",
            "price": 10.70,
            "pct": 7.0,
            "amount": 20_000_000,
            "turnover": 0.35,
            "volumeRatio": None,
            "high": 10.72,
            "low": 10.10,
            "open": 10.20,
            "preClose": 10.00,
            "avgPrice": 10.45,
            "amplitude": 6.2,
            "mainNet": 3_000_000,
            "superNet": 1_000_000,
            "industry": "早盘行业",
        }
        item = STRATEGY.evaluate_stock_snapshot(
            quote,
            strong_board(),
            {STRATEGY.STRATEGY_AM_TOP},
            now,
            {"emotionScore": 70, "riskLevel": "NORMAL", "marketGatePassed": True},
        )
        self.assertIsNotNone(item)
        self.assertEqual(item["strategyTag"], STRATEGY.STRATEGY_AM_TOP)
        self.assertFalse(item["actionable"])
        self.assertEqual(item["executionMode"], "WATCH_ONLY")
        self.assertLess(STRATEGY.morning_min_amount(now), 80_000_000)

    def test_early_lift_off_branch_is_no_longer_recommended(self):
        now = datetime(2026, 7, 16, 9, 32, tzinfo=STRATEGY.CN_TZ)
        quote = tail_quote(
            code="000002",
            price=10.58,
            pct=5.8,
            amount=20_000_000,
            turnover=0.35,
            volumeRatio=None,
            high=10.60,
            low=10.10,
            open=10.20,
            preClose=10.00,
            avgPrice=10.40,
        )
        item = STRATEGY.evaluate_stock_snapshot(
            quote,
            strong_board(),
            {STRATEGY.STRATEGY_AM_TOP},
            now,
            {"emotionScore": 70, "riskLevel": "NORMAL", "marketGatePassed": True},
        )
        self.assertIsNone(item)

    def test_unverified_synthetic_board_cannot_qualify_am_top(self):
        quote = tail_quote(industry="unmatched")
        board = STRATEGY.am_top_board_for_quote(quote)
        self.assertFalse(board["qualified"])
        self.assertEqual(board["passed"], 0)

    def test_all_share_scan_requires_a_verified_matching_board(self):
        now = datetime(2026, 7, 16, 9, 32, tzinfo=STRATEGY.CN_TZ)
        quote = tail_quote(
            code="000002",
            price=10.70,
            pct=7.0,
            amount=20_000_000,
            turnover=0.35,
            volumeRatio=None,
            high=10.72,
            low=10.10,
            open=10.20,
            preClose=10.00,
            avgPrice=10.45,
            industry="unmatched",
        )
        recommendations = STRATEGY.build_recommendations(
            [],
            now,
            [quote],
            {"emotionScore": 70, "riskLevel": "NORMAL", "marketGatePassed": True},
        )
        self.assertEqual(recommendations, [])

    def test_strategy_windows_do_not_emit_at_night(self):
        night = datetime(2026, 7, 16, 20, 0, tzinfo=STRATEGY.CN_TZ)
        self.assertEqual(STRATEGY.active_strategy_windows(night), set())

    def test_market_breadth_hard_veto_blocks_crash_state(self):
        winners = [tail_quote(code=f"600{i:03d}", pct=9.9) for i in range(35)]
        losers = [tail_quote(code=f"000{i:03d}", pct=-8.0) for i in range(70)]
        monitor = STRATEGY.build_market_monitor([*winners, *losers], [strong_board()])
        self.assertTrue(monitor["hardVeto"])
        self.assertEqual(monitor["riskLevel"], "RISK_OFF")


if __name__ == "__main__":
    unittest.main()
