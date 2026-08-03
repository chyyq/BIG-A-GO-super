import importlib.util
import base64
import gzip
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "learning_store.py"
SPEC = importlib.util.spec_from_file_location("learning_store", MODULE_PATH)
learning_store = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(learning_store)


class TradeExportImportTests(unittest.TestCase):
    def test_sync_code_accepts_valid_json_when_only_gzip_footer_is_damaged(self):
        payload = {"version": 3, "trades": [{"code": "600000"}]}
        raw = bytearray(gzip.compress(json.dumps(payload).encode("utf-8")))
        raw[-8] ^= 1
        token = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

        decoded = learning_store.decode_sync_code(f"BAGS3G.{token}")

        self.assertEqual(decoded, payload)

    def test_only_explicit_web_outcome_becomes_a_label(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reference = root / "reference"
            reference.mkdir()
            export_path = reference / "BIG-A-GO-trades-2026-07-26.json"
            sample_path = root / "learning" / "samples.json"
            learning_store.ROOT = root
            learning_store.SAMPLES_PATH = sample_path

            trade = {
                "id": "trade-1",
                "code": "600000",
                "name": "同步样本",
                "buyPrice": 10,
                "stopLoss": 9.6,
                "takeProfit": 10.5,
                "status": "open",
                "buyTradingDate": "2026-07-24",
                "plannedSellTradingDate": "2026-07-27",
                "createdAt": "2026-07-24T14:20:00+08:00",
                "updatedAt": "2026-07-24T14:20:00+08:00",
            }
            payload = {"version": 3, "exportedAt": "2026-07-26T10:00:00+08:00", "trades": [trade]}
            export_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            exports = [
                {
                    "exportId": "export-1",
                    "path": export_path.relative_to(root).as_posix(),
                }
            ]

            result = learning_store.sync_trade_exports(exports)
            samples = json.loads(sample_path.read_text(encoding="utf-8"))["samples"]
            self.assertEqual(result["added"], 1)
            self.assertEqual(samples[0]["outcome"], "unknown")
            self.assertIn("actual_outcome", samples[0]["missingEvidence"])

            trade.update(
                {
                    "status": "closed",
                    "outcome": "take_profit",
                    "strategyTag": "AM_TOP",
                    "reviewSnapshot": {"buyDayLimitOutcome": "SEALED_AT_CLOSE"},
                    "sellTradingDate": "2026-07-27",
                    "resultMarkedAt": "2026-07-27T09:40:00+08:00",
                    "updatedAt": "2026-07-27T09:40:00+08:00",
                }
            )
            payload["exportedAt"] = "2026-07-27T10:00:00+08:00"
            export_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            learning_store.sync_trade_exports(exports)
            updated = json.loads(sample_path.read_text(encoding="utf-8"))["samples"][0]
            self.assertEqual(updated["outcome"], "take_profit")
            self.assertEqual(updated["outcomeSource"], "web_explicit_mark")
            self.assertEqual(updated["entryStrategy"], "AM_TOP")
            self.assertEqual(updated["buyDayLimitOutcome"], "SEALED_AT_CLOSE")
            self.assertNotIn("actual_outcome", updated["missingEvidence"])

    def test_not_sealed_statement_counts_only_for_seal_rate(self):
        samples = [
            {
                "sampleId": "20260727-600000",
                "stockCode": "600000",
                "buyDate": "2026-07-27",
                "sellDate": "2026-07-28",
                "outcome": "take_profit",
                "entryStrategy": "AM_TOP",
                "buyDayLimitOutcome": "NOT_SEALED_AT_CLOSE",
                "prices": {"buy": 10, "actualSell": 9.5},
                "missingEvidence": [],
            }
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            learning_store.ROOT = root
            learning_store.SAMPLES_PATH = root / "learning" / "samples.json"
            learning_store.MODEL_PATH = root / "learning" / "model_state.json"
            learning_store.REPORT_PATH = root / "learning" / "reports" / "latest.md"
            learning_store.EVENTS_PATH = root / "learning" / "history" / "events.jsonl"
            learning_store.CATALOG_PATH = root / "learning" / "catalog.json"
            learning_store.write_json(
                learning_store.SAMPLES_PATH,
                {"schemaVersion": 1, "samples": samples, "ruleCandidates": []},
            )

            model = learning_store.rebuild_model()

            stats = model["entryStrategies"]["AM_TOP"]
            self.assertEqual(stats["buyDayLimitKnown"], 1)
            self.assertEqual(stats["buyDayLimitTouchKnown"], 0)
            self.assertIsNone(stats["buyDayLimitTouchRate"])
            self.assertEqual(stats["buyDayLimitSealRate"], 0.0)
            self.assertEqual(stats["realizedReturnKnown"], 1)
            self.assertEqual(stats["averageRealizedReturnPct"], -5.0)
            self.assertEqual(model["averageRealizedReturnPct"], -5.0)


if __name__ == "__main__":
    unittest.main()
