from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DIR = ROOT / "reference"
LEARNING_DIR = ROOT / "learning"
CATALOG_PATH = LEARNING_DIR / "catalog.json"
SAMPLES_PATH = LEARNING_DIR / "samples.json"
MODEL_PATH = LEARNING_DIR / "model_state.json"
REPORT_PATH = LEARNING_DIR / "reports" / "latest.md"
EVENTS_PATH = LEARNING_DIR / "history" / "events.jsonl"
EXPORT_JSON_PATH = LEARNING_DIR / "exports" / "latest.json"
EXPORT_CSV_PATH = LEARNING_DIR / "exports" / "trades.csv"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
TRADE_EXPORT_PREFIX = "BIG-A-GO-trades-"
ASSET_TYPES = {
    "买入盘": "buy",
    "卖出盘": "sell",
    "五日盘": "five_day",
    "五日": "five_day",
    "夜间复盘": "night_review",
    "夜间策略": "night_review",
    "夜盘策略": "night_review",
    "大盘": "market",
    "形态": "shape",
}
NAME_ALIASES = {"山东波纤": "山东玻纤"}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def append_event(event_type: str, details: dict[str, Any]) -> None:
    EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    event = {"at": now_iso(), "type": event_type, **details}
    with EVENTS_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def classify_asset(filename: str) -> str:
    for marker, asset_type in ASSET_TYPES.items():
        if marker in filename:
            return asset_type
    return "other"


def infer_dates(text: str, year: int) -> list[str]:
    compact = re.findall(r"(?<!\d)(\d{4})(?!\d)", text)
    dotted = re.findall(r"(?<!\d)(\d{1,2})[._-](\d{1,2})(?!\d)", text)
    values: list[str] = []
    for value in compact:
        month, day = int(value[:2]), int(value[2:])
        try:
            values.append(date(year, month, day).isoformat())
        except ValueError:
            continue
    for month_text, day_text in dotted:
        try:
            values.append(date(year, int(month_text), int(day_text)).isoformat())
        except ValueError:
            continue
    return list(dict.fromkeys(values))


def infer_stock_names(filename: str, asset_type: str) -> list[str]:
    if asset_type == "market":
        return []
    stem = Path(filename).stem
    stem = re.sub(r"^[（(][^）)]+[）)]", "", stem)
    stem = re.split(r"[-_](?:买入盘|卖出盘|五日盘|夜间复盘|夜间策略|夜盘策略)", stem, maxsplit=1)[0]
    stem = re.sub(r"(?:\d{1,2}[._-]\d{1,2}|\d{4}).*$", "", stem)
    stem = stem.replace("形态", "").strip("-_ ")
    names = [part.strip() for part in re.split(r"[+＋]", stem) if part.strip()]
    return [NAME_ALIASES.get(name, name) for name in names]


def read_trade_export(path: Path) -> dict[str, Any] | None:
    if path.suffix.lower() != ".json" or not path.name.startswith(TRADE_EXPORT_PREFIX):
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) and isinstance(payload.get("trades"), list) else None


def scan_reference(year: int) -> dict[str, Any]:
    previous = load_json(CATALOG_PATH, {"assets": []})
    previous_by_hash = {item["sha256"]: item for item in previous.get("assets", [])}
    previous_exports_by_hash = {
        item["sha256"]: item for item in previous.get("tradeExports", [])
    }
    assets: list[dict[str, Any]] = []
    trade_exports: list[dict[str, Any]] = []
    new_count = 0
    new_trade_export_count = 0
    for path in sorted(REFERENCE_DIR.rglob("*")):
        if not path.is_file():
            continue
        trade_payload = read_trade_export(path)
        if trade_payload is not None:
            digest = file_sha256(path)
            old = previous_exports_by_hash.get(digest)
            if old is None:
                new_trade_export_count += 1
            trade_exports.append(
                {
                    "exportId": digest[:16],
                    "sha256": digest,
                    "path": path.relative_to(ROOT).as_posix(),
                    "exportedAt": trade_payload.get("exportedAt"),
                    "tradeCount": len(trade_payload["trades"]),
                    "firstSeenAt": old.get("firstSeenAt") if old else now_iso(),
                    "lastSeenAt": now_iso(),
                }
            )
            continue
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        digest = file_sha256(path)
        relative = path.relative_to(ROOT).as_posix()
        asset_type = classify_asset(path.name)
        old = previous_by_hash.get(digest)
        if old is None:
            new_count += 1
        assets.append(
            {
                "assetId": digest[:16],
                "sha256": digest,
                "path": relative,
                "type": asset_type,
                "stockNames": infer_stock_names(path.name, asset_type),
                "dates": infer_dates(relative, year),
                "size": path.stat().st_size,
                "firstSeenAt": old.get("firstSeenAt") if old else now_iso(),
                "lastSeenAt": now_iso(),
            }
        )
    payload = {
        "schemaVersion": 1,
        "scannedAt": now_iso(),
        "referenceRoot": "reference",
        "assetCount": len(assets),
        "newAssetCount": new_count,
        "assets": assets,
        "tradeExportCount": len(trade_exports),
        "newTradeExportCount": new_trade_export_count,
        "tradeExports": trade_exports,
    }
    write_json(CATALOG_PATH, payload)
    sync_result = sync_trade_exports(trade_exports)
    append_event(
        "scan",
        {
            "assetCount": len(assets),
            "newAssetCount": new_count,
            "tradeExportCount": len(trade_exports),
            "newTradeExportCount": new_trade_export_count,
            "tradeSamplesAdded": sync_result["added"],
            "tradeSamplesUpdated": sync_result["updated"],
        },
    )
    return payload


def parse_timestamp(value: Any) -> float:
    if not value:
        return 0
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0


def trade_modified_at(trade: dict[str, Any], exported_at: Any) -> float:
    return max(
        [
            parse_timestamp(trade.get(field))
            for field in ("resultMarkedAt", "updatedAt", "soldAt", "createdAt")
        ]
        + [parse_timestamp(exported_at)]
    )


def sync_trade_exports(trade_exports: list[dict[str, Any]]) -> dict[str, int]:
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for export in trade_exports:
        path = ROOT / export["path"]
        payload = read_trade_export(path)
        if payload is None:
            continue
        for trade in payload["trades"]:
            if not isinstance(trade, dict):
                continue
            code = str(trade.get("code") or "").strip()
            buy_date = str(trade.get("buyTradingDate") or "").strip()
            if not code or not buy_date:
                continue
            candidate = {
                "trade": trade,
                "exportId": export["exportId"],
                "exportedAt": payload.get("exportedAt"),
                "modifiedAt": trade_modified_at(trade, payload.get("exportedAt")),
            }
            key = (code, buy_date)
            if candidate["modifiedAt"] >= latest.get(key, {}).get("modifiedAt", -1):
                latest[key] = candidate

    source = load_json(
        SAMPLES_PATH,
        {"schemaVersion": 1, "updatedAt": now_iso(), "samples": [], "ruleCandidates": []},
    )
    samples = source.setdefault("samples", [])
    by_key = {
        (str(sample.get("stockCode") or ""), str(sample.get("buyDate") or "")): sample
        for sample in samples
    }
    added = updated = 0
    for (code, buy_date), candidate in latest.items():
        trade = candidate["trade"]
        sell_date = str(
            trade.get("sellTradingDate")
            or trade.get("plannedSellTradingDate")
            or ""
        ).strip()
        if not sell_date:
            continue
        explicit_outcome = (
            trade.get("outcome")
            if trade.get("outcome") in {"take_profit", "stop_loss", "manual_exit"}
            else None
        )
        sample = by_key.get((code, buy_date))
        if sample is None:
            sample = {
                "sampleId": f"{buy_date.replace('-', '')}-{code}",
                "stockCode": code,
                "stockName": str(trade.get("name") or "").strip(),
                "buyDate": buy_date,
                "sellDate": sell_date,
                "outcome": explicit_outcome or "unknown",
                "openingRegime": "unknown",
                "prices": {},
                "market": {},
                "nightPlan": {},
                "sourceAssetIds": [],
                "sourceTradeExportIds": [],
                "missingEvidence": [
                    "buy",
                    "sell",
                    "five_day",
                    "night_review",
                    "market_buy",
                    "market_sell",
                    "actual_outcome",
                ],
                "diagnosis": "",
            }
            samples.append(sample)
            by_key[(code, buy_date)] = sample
            added += 1
        else:
            updated += 1

        sample["stockName"] = sample.get("stockName") or str(trade.get("name") or "").strip()
        sample["sellDate"] = trade.get("sellTradingDate") or sample.get("sellDate") or sell_date
        prices = sample.setdefault("prices", {})
        if prices.get("buy") is None and trade.get("buyPrice") is not None:
            prices["buy"] = as_number(trade.get("buyPrice"))
        if trade.get("sellPrice") is not None:
            prices["actualSell"] = as_number(trade.get("sellPrice"))
        night_plan = sample.setdefault("nightPlan", {})
        if night_plan.get("tp1") is None and trade.get("takeProfit") is not None:
            night_plan["tp1"] = as_number(trade.get("takeProfit"))
        if night_plan.get("stop") is None and trade.get("stopLoss") is not None:
            night_plan["stop"] = as_number(trade.get("stopLoss"))
        source_ids = sample.setdefault("sourceTradeExportIds", [])
        if candidate["exportId"] not in source_ids:
            source_ids.append(candidate["exportId"])
        if explicit_outcome:
            sample["outcome"] = explicit_outcome
            sample["outcomeSource"] = "web_explicit_mark"
            sample["missingEvidence"] = [
                item for item in sample.get("missingEvidence", []) if item != "actual_outcome"
            ]
        elif sample.get("outcome") not in {"take_profit", "stop_loss", "manual_exit"}:
            sample["outcome"] = "unknown"
            if "actual_outcome" not in sample.get("missingEvidence", []):
                sample.setdefault("missingEvidence", []).append("actual_outcome")
        sample["webTrade"] = {
            "tradeId": trade.get("id"),
            "status": trade.get("status"),
            "plannedSellDate": trade.get("plannedSellTradingDate"),
            "actualSellDate": trade.get("sellTradingDate"),
            "resultMarkedAt": trade.get("resultMarkedAt"),
            "exportedAt": candidate["exportedAt"],
        }

    if latest:
        source["updatedAt"] = now_iso()
        write_json(SAMPLES_PATH, source)
    return {"added": added, "updated": updated}


def as_number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def pct_change(high_or_low: Any, base: Any) -> float | None:
    price = as_number(high_or_low)
    anchor = as_number(base)
    if not price or not anchor:
        return None
    return round(((price / anchor) - 1) * 100, 2)


def safe_rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 2) if denominator else None


def validate_sample(sample: dict[str, Any], asset_ids: set[str]) -> list[str]:
    issues: list[str] = []
    sample_id = sample.get("sampleId") or "UNKNOWN"
    buy_date = sample.get("buyDate")
    sell_date = sample.get("sellDate")
    if not buy_date or not sell_date:
        issues.append(f"{sample_id}: missing buyDate or sellDate")
    else:
        try:
            if date.fromisoformat(sell_date) <= date.fromisoformat(buy_date):
                issues.append(f"{sample_id}: sellDate must be after buyDate")
        except ValueError:
            issues.append(f"{sample_id}: invalid ISO date")
    if sample.get("outcome") not in {"take_profit", "stop_loss", "manual_exit", "unknown"}:
        issues.append(f"{sample_id}: invalid outcome")
    missing_assets = [asset_id for asset_id in sample.get("sourceAssetIds", []) if asset_id not in asset_ids]
    if missing_assets:
        issues.append(f"{sample_id}: unknown source assets {', '.join(missing_assets)}")
    return issues


def rebuild_model() -> dict[str, Any]:
    catalog = load_json(CATALOG_PATH, {"assets": []})
    source = load_json(SAMPLES_PATH, {"samples": [], "ruleCandidates": []})
    samples = source.get("samples", [])
    asset_ids = {asset["assetId"] for asset in catalog.get("assets", [])}
    issues = [issue for sample in samples for issue in validate_sample(sample, asset_ids)]

    labeled = [sample for sample in samples if sample.get("outcome") != "unknown"]
    outcomes = Counter(sample.get("outcome") for sample in labeled)
    missing_evidence = Counter(
        item
        for sample in samples
        for item in sample.get("missingEvidence", [])
    )
    computed: list[dict[str, Any]] = []
    tp1_known = tp1_hits = 0
    stop_known = stop_hits = 0
    mfe3_known = mfe3_hits = 0
    by_opening: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for sample in samples:
        prices = sample.get("prices") or {}
        plan = sample.get("nightPlan") or {}
        mfe = pct_change(prices.get("nextHigh"), prices.get("buy"))
        mae = pct_change(prices.get("nextLow"), prices.get("buy"))
        tp1_range = plan.get("tp1Range") or []
        tp1_low = as_number(tp1_range[0]) if tp1_range else as_number(plan.get("tp1"))
        stop = as_number(plan.get("stop"))
        next_high = as_number(prices.get("nextHigh"))
        next_low = as_number(prices.get("nextLow"))
        tp1_hit = next_high >= tp1_low if next_high is not None and tp1_low is not None else None
        stop_hit = next_low <= stop if next_low is not None and stop is not None else None
        if tp1_hit is not None:
            tp1_known += 1
            tp1_hits += int(tp1_hit)
        if stop_hit is not None:
            stop_known += 1
            stop_hits += int(stop_hit)
        if mfe is not None:
            mfe3_known += 1
            mfe3_hits += int(mfe >= 3)
        row = {
            "sampleId": sample.get("sampleId"),
            "mfePct": mfe,
            "maePct": mae,
            "tp1Hit": tp1_hit,
            "stopHit": stop_hit,
        }
        computed.append(row)
        by_opening[sample.get("openingRegime") or "unknown"].append({**sample, **row})

    opening_stats = {}
    for regime, rows in sorted(by_opening.items()):
        regime_labeled = [row for row in rows if row.get("outcome") != "unknown"]
        regime_wins = sum(row.get("outcome") == "take_profit" for row in regime_labeled)
        opening_stats[regime] = {
            "samples": len(rows),
            "labeled": len(regime_labeled),
            "takeProfitRate": safe_rate(regime_wins, len(regime_labeled)),
            "averageMfePct": round(
                sum(row["mfePct"] for row in rows if row.get("mfePct") is not None)
                / max(1, sum(row.get("mfePct") is not None for row in rows)),
                2,
            ),
        }

    rule_candidates = []
    for rule in source.get("ruleCandidates", []):
        evidence_ids = set(rule.get("supportSampleIds", [])) | set(rule.get("contradictionSampleIds", []))
        evidence_samples = [sample for sample in samples if sample.get("sampleId") in evidence_ids]
        distinct_dates = len({sample.get("buyDate") for sample in evidence_samples if sample.get("buyDate")})
        evidence_count = len(evidence_samples)
        labeled_evidence_count = sum(sample.get("outcome") != "unknown" for sample in evidence_samples)
        minimum = int(rule.get("minimumSamples") or 8)
        rule_candidates.append(
            {
                **rule,
                "evidenceCount": evidence_count,
                "labeledEvidenceCount": labeled_evidence_count,
                "distinctBuyDates": distinct_dates,
                "promotionReady": (
                    evidence_count >= minimum
                    and distinct_dates >= 3
                    and labeled_evidence_count >= math.ceil(minimum / 2)
                ),
            }
        )

    model = {
        "schemaVersion": 1,
        "rebuiltAt": now_iso(),
        "sampleCount": len(samples),
        "labeledSampleCount": len(labeled),
        "pendingOutcomeCount": len(samples) - len(labeled),
        "outcomes": dict(outcomes),
        "missingEvidence": dict(sorted(missing_evidence.items())),
        "takeProfitRate": safe_rate(outcomes["take_profit"], len(labeled)),
        "tp1HitRate": safe_rate(tp1_hits, tp1_known),
        "stopHitRate": safe_rate(stop_hits, stop_known),
        "mfeAtLeast3Rate": safe_rate(mfe3_hits, mfe3_known),
        "openingRegimes": opening_stats,
        "computedSamples": computed,
        "ruleCandidates": rule_candidates,
        "validationIssues": issues,
    }
    write_json(MODEL_PATH, model)
    write_report(model, catalog)
    append_event(
        "rebuild",
        {
            "sampleCount": len(samples),
            "labeledSampleCount": len(labeled),
            "validationIssueCount": len(issues),
        },
    )
    return model


def export_learning_data() -> dict[str, Any]:
    catalog = load_json(CATALOG_PATH, {"assets": []})
    source = load_json(SAMPLES_PATH, {"samples": [], "ruleCandidates": []})
    model = load_json(MODEL_PATH, {})
    payload = {
        "schemaVersion": 1,
        "exportedAt": now_iso(),
        "catalog": catalog,
        "samples": source,
        "modelState": model,
    }
    write_json(EXPORT_JSON_PATH, payload)
    EXPORT_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    computed = {
        row.get("sampleId"): row
        for row in model.get("computedSamples", [])
    }
    fields = [
        "sampleId",
        "stockCode",
        "stockName",
        "buyDate",
        "sellDate",
        "outcome",
        "openingRegime",
        "buyPrice",
        "nextOpen",
        "nextHigh",
        "nextLow",
        "nextClose",
        "mfePct",
        "maePct",
        "tp1Hit",
        "stopHit",
        "missingEvidence",
    ]
    with EXPORT_CSV_PATH.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for sample in source.get("samples", []):
            prices = sample.get("prices") or {}
            derived = computed.get(sample.get("sampleId"), {})
            writer.writerow(
                {
                    "sampleId": sample.get("sampleId"),
                    "stockCode": sample.get("stockCode"),
                    "stockName": sample.get("stockName"),
                    "buyDate": sample.get("buyDate"),
                    "sellDate": sample.get("sellDate"),
                    "outcome": sample.get("outcome"),
                    "openingRegime": sample.get("openingRegime"),
                    "buyPrice": prices.get("buy"),
                    "nextOpen": prices.get("nextOpen"),
                    "nextHigh": prices.get("nextHigh"),
                    "nextLow": prices.get("nextLow"),
                    "nextClose": prices.get("nextClose"),
                    "mfePct": derived.get("mfePct"),
                    "maePct": derived.get("maePct"),
                    "tp1Hit": derived.get("tp1Hit"),
                    "stopHit": derived.get("stopHit"),
                    "missingEvidence": "|".join(sample.get("missingEvidence", [])),
                }
            )
    append_event("export", {"json": str(EXPORT_JSON_PATH.relative_to(ROOT)), "csv": str(EXPORT_CSV_PATH.relative_to(ROOT))})
    return payload


def display_rate(value: Any) -> str:
    return "--" if value is None else f"{value:.2f}%"


def write_report(model: dict[str, Any], catalog: dict[str, Any]) -> None:
    lines = [
        "# 本地学习状态",
        "",
        f"- 更新时间：{model['rebuiltAt']}",
        f"- 已归档图片：{catalog.get('assetCount', 0)}",
        f"- 已识别网页交易快照：{catalog.get('tradeExportCount', 0)}",
        f"- 结构化交易样本：{model['sampleCount']}",
        f"- 已标注结果：{model['labeledSampleCount']}",
        f"- 待补结果：{model['pendingOutcomeCount']}",
        f"- 实际止盈率：{display_rate(model['takeProfitRate'])}",
        f"- 第一止盈区命中率：{display_rate(model['tp1HitRate'])}",
        f"- 次日最大涨幅达到3%：{display_rate(model['mfeAtLeast3Rate'])}",
        "",
        "## 开盘形态",
        "",
        "| 形态 | 样本 | 已标注 | 止盈率 | 平均MFE |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, stats in model["openingRegimes"].items():
        lines.append(
            f"| {name} | {stats['samples']} | {stats['labeled']} | "
            f"{display_rate(stats['takeProfitRate'])} | {stats['averageMfePct']:.2f}% |"
        )
    lines.extend(["", "## 规则候选", ""])
    for rule in model["ruleCandidates"]:
        state = "达到复核门槛" if rule["promotionReady"] else "继续积累"
        lines.append(
            f"- `{rule['id']}`：{state}，证据 {rule['evidenceCount']} 笔，"
            f"其中真实结果 {rule['labeledEvidenceCount']} 笔，覆盖 {rule['distinctBuyDates']} 个买入日。"
        )
    if model["validationIssues"]:
        lines.extend(["", "## 待修正数据", ""])
        lines.extend(f"- {issue}" for issue in model["validationIssues"])
    if model["missingEvidence"]:
        lines.extend(["", "## 缺失证据", ""])
        lines.extend(f"- `{name}`：{count} 笔" for name, count in model["missingEvidence"].items())
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def print_status(catalog: dict[str, Any], model: dict[str, Any]) -> None:
    print(
        json.dumps(
            {
                "assets": catalog.get("assetCount", 0),
                "newAssets": catalog.get("newAssetCount", 0),
                "tradeExports": catalog.get("tradeExportCount", 0),
                "newTradeExports": catalog.get("newTradeExportCount", 0),
                "samples": model.get("sampleCount", 0),
                "labeled": model.get("labeledSampleCount", 0),
                "pending": model.get("pendingOutcomeCount", 0),
                "takeProfitRate": model.get("takeProfitRate"),
                "validationIssues": model.get("validationIssues", []),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Local evidence store for the T+1 learning workflow")
    parser.add_argument("command", choices=("scan", "rebuild", "export", "run", "status"))
    parser.add_argument("--year", type=int, default=datetime.now().year)
    args = parser.parse_args()

    LEARNING_DIR.mkdir(parents=True, exist_ok=True)
    if args.command in {"scan", "run"}:
        catalog = scan_reference(args.year)
    else:
        catalog = load_json(CATALOG_PATH, {"assets": []})
    if args.command in {"rebuild", "run"}:
        model = rebuild_model()
    else:
        model = load_json(MODEL_PATH, {})
    if args.command in {"export", "run"}:
        export_learning_data()
    print_status(catalog, model)


if __name__ == "__main__":
    main()
