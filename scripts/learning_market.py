from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import parse, request


ROOT = Path(__file__).resolve().parents[1]
SAMPLES_PATH = ROOT / "learning" / "samples.json"
EVIDENCE_DIR = ROOT / "learning" / "market_evidence"
EVENTS_PATH = ROOT / "learning" / "history" / "events.jsonl"
EASTMONEY_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
INDEX_SECIDS = {"shanghai": "1.000001", "shenzhen": "0.399001"}
INDEX_SYMBOLS = {"shanghai": "000001.SS", "shenzhen": "399001.SZ"}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def append_event(details: dict[str, Any]) -> None:
    EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": now_iso(), "type": "market_evidence", **details}, ensure_ascii=False) + "\n")


def number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def rounded(value: Any, digits: int = 2) -> float | None:
    result = number(value)
    return round(result, digits) if result is not None else None


def pct(value: Any, base: Any) -> float | None:
    value_number = number(value)
    base_number = number(base)
    if value_number is None or not base_number:
        return None
    return round((value_number / base_number - 1) * 100, 2)


def mean(values: list[Any]) -> float | None:
    valid = [value for item in values if (value := number(item)) is not None]
    return sum(valid) / len(valid) if valid else None


def get_json(url: str, retries: int = 3) -> dict[str, Any]:
    headers = {
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://quote.eastmoney.com/",
        "User-Agent": "Mozilla/5.0",
    }
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with request.urlopen(request.Request(url, headers=headers), timeout=25) as response:
                return json.loads(response.read().decode("utf-8", "ignore"))
        except Exception as exc:  # Network providers occasionally close idle connections.
            last_error = exc
            time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(str(last_error or "request failed"))


def secid_for_stock(code: str) -> str:
    return f"{1 if code.startswith('6') else 0}.{code}"


def yahoo_symbol(code: str) -> str:
    return f"{code}.{'SS' if code.startswith('6') else 'SZ'}"


def fetch_daily(secid: str, begin: str, end: str) -> tuple[list[dict[str, Any]], str]:
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "1",
        "beg": begin.replace("-", ""),
        "end": end.replace("-", ""),
        "lmt": "60",
    }
    url = f"{EASTMONEY_URL}?{parse.urlencode(params)}"
    payload = get_json(url)
    rows = []
    for line in ((payload.get("data") or {}).get("klines") or []):
        parts = line.split(",")
        if len(parts) < 11:
            continue
        rows.append(
            {
                "date": parts[0],
                "open": number(parts[1]),
                "close": number(parts[2]),
                "high": number(parts[3]),
                "low": number(parts[4]),
                "volume": number(parts[5]),
                "amount": number(parts[6]),
                "amplitudePct": number(parts[7]),
                "changePct": number(parts[8]),
                "turnoverPct": number(parts[10]),
            }
        )
    return rows, url


def fetch_intraday(code: str, trading_date: str) -> tuple[list[dict[str, Any]], str]:
    start = int(datetime.fromisoformat(f"{trading_date}T00:00:00+08:00").timestamp())
    end = start + 86400
    params = {"period1": start, "period2": end, "interval": "5m", "events": "history"}
    url = f"{YAHOO_URL.format(symbol=yahoo_symbol(code))}?{parse.urlencode(params)}"
    payload = get_json(url)
    result = ((payload.get("chart") or {}).get("result") or [None])[0] or {}
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    rows = []
    for index, stamp in enumerate(timestamps):
        moment = datetime.fromtimestamp(stamp).astimezone()
        if moment.date().isoformat() != trading_date:
            continue
        rows.append(
            {
                "time": moment.strftime("%H:%M"),
                "open": number((quote.get("open") or [])[index]),
                "high": number((quote.get("high") or [])[index]),
                "low": number((quote.get("low") or [])[index]),
                "close": number((quote.get("close") or [])[index]),
                "volume": number((quote.get("volume") or [])[index]),
            }
        )
    return rows, url


def fetch_yahoo_daily(symbol: str, begin: str, end: str) -> tuple[list[dict[str, Any]], str]:
    start = int(datetime.fromisoformat(f"{begin}T00:00:00+08:00").timestamp())
    finish = int(datetime.fromisoformat(f"{end}T00:00:00+08:00").timestamp()) + 86400
    params = {"period1": start, "period2": finish, "interval": "1d", "events": "history"}
    url = f"{YAHOO_URL.format(symbol=symbol)}?{parse.urlencode(params)}"
    payload = get_json(url)
    result = ((payload.get("chart") or {}).get("result") or [None])[0] or {}
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    rows = []
    previous_close = None
    for index, stamp in enumerate(timestamps):
        row = {
            "date": datetime.fromtimestamp(stamp).astimezone().date().isoformat(),
            "open": number((quote.get("open") or [])[index]),
            "close": number((quote.get("close") or [])[index]),
            "high": number((quote.get("high") or [])[index]),
            "low": number((quote.get("low") or [])[index]),
            "volume": number((quote.get("volume") or [])[index]),
            "amount": None,
            "amplitudePct": None,
            "changePct": None,
            "turnoverPct": None,
        }
        row["changePct"] = pct(row["close"], previous_close)
        if row["close"] is not None:
            previous_close = row["close"]
        rows.append(row)
    return rows, url


def row_for_date(rows: list[dict[str, Any]], trading_date: str) -> dict[str, Any] | None:
    return next((row for row in rows if row.get("date") == trading_date), None)


def daily_summary(rows: list[dict[str, Any]], trading_date: str) -> dict[str, Any] | None:
    index = next((i for i, row in enumerate(rows) if row.get("date") == trading_date), None)
    if index is None:
        return None
    row = rows[index]
    prior = rows[max(0, index - 5) : index]
    ma5 = mean([item.get("close") for item in rows[max(0, index - 4) : index + 1]])
    previous_ma5 = mean([item.get("close") for item in rows[max(0, index - 5) : index]])
    price_range = (row.get("high") or 0) - (row.get("low") or 0)
    close_location = ((row.get("close") - row.get("low")) / price_range * 100) if price_range else None
    upper_shadow = ((row.get("high") - max(row.get("open"), row.get("close"))) / price_range * 100) if price_range else None
    prior_amount = mean([item.get("amount") for item in prior])
    prior_volume = mean([item.get("volume") for item in prior])
    return {
        **row,
        "ma5": rounded(ma5),
        "previousMa5": rounded(previous_ma5),
        "ma5Rising": ma5 is not None and previous_ma5 is not None and ma5 >= previous_ma5,
        "closeVsMa5Pct": pct(row.get("close"), ma5),
        "amountRatio5": rounded(row.get("amount") / prior_amount if row.get("amount") and prior_amount else None),
        "volumeRatio5": rounded(row.get("volume") / prior_volume if row.get("volume") and prior_volume else None),
        "closeLocationPct": rounded(close_location),
        "upperShadowPctOfRange": rounded(upper_shadow),
    }


def price_at_or_before(rows: list[dict[str, Any]], target: str) -> float | None:
    values = [row.get("close") for row in rows if row.get("time", "") <= target and row.get("close") is not None]
    return values[-1] if values else None


def intraday_summary(rows: list[dict[str, Any]], buy_price: float | None, previous_close: float | None) -> dict[str, Any] | None:
    before_ten = [row for row in rows if "09:30" <= row.get("time", "") <= "10:00"]
    if not before_ten:
        return None
    highs = [(row.get("high"), row.get("time")) for row in before_ten if row.get("high") is not None]
    lows = [row.get("low") for row in before_ten if row.get("low") is not None]
    peak, peak_time = max(highs) if highs else (None, None)
    trough = min(lows) if lows else None
    open_price = before_ten[0].get("open")
    close_1000 = price_at_or_before(before_ten, "10:00")
    return {
        "open": rounded(open_price, 3),
        "gapPct": pct(open_price, previous_close),
        "highBefore1000": rounded(peak, 3),
        "lowBefore1000": rounded(trough, 3),
        "close0935": rounded(price_at_or_before(before_ten, "09:35"), 3),
        "close0945": rounded(price_at_or_before(before_ten, "09:45"), 3),
        "close1000": rounded(close_1000, 3),
        "peakTime": peak_time,
        "mfeBefore1000Pct": pct(peak, buy_price),
        "maeBefore1000Pct": pct(trough, buy_price),
        "fadeFromPeakPct": pct(close_1000, peak),
    }


def classify_opening(summary: dict[str, Any] | None) -> str:
    if not summary:
        return "unknown"
    gap = summary.get("gapPct") or 0
    fade = summary.get("fadeFromPeakPct") or 0
    close_1000 = summary.get("close1000")
    open_price = summary.get("open")
    held_open = close_1000 is not None and open_price is not None and close_1000 >= open_price
    if gap >= 1:
        return "strong_open_extension" if held_open and fade >= -1 else "gap_up_failed_followthrough"
    if gap <= -1:
        return "gap_down_recovery" if held_open else "gap_down_weak"
    return "flat_open_followthrough" if held_open else "flat_open_failed_followthrough"


def market_day(index_rows: dict[str, list[dict[str, Any]]], trading_date: str) -> dict[str, Any]:
    result = {}
    for name, rows in index_rows.items():
        row = row_for_date(rows, trading_date)
        if row:
            result[name] = {key: row.get(key) for key in ("open", "close", "high", "low", "changePct")}
    result["averageChangePct"] = rounded(mean([item.get("changePct") for item in result.values() if isinstance(item, dict)]))
    return result


def enrich_sample(sample: dict[str, Any], index_rows: dict[str, list[dict[str, Any]]]) -> tuple[dict[str, Any], list[str]]:
    code = str(sample.get("stockCode") or "")
    buy_date = str(sample.get("buyDate") or "")
    sell_date = str(sample.get("sellDate") or "")
    errors = []
    daily_rows: list[dict[str, Any]] = []
    daily_url = ""
    daily_provider = "Yahoo Finance"
    try:
        daily_rows, daily_url = fetch_yahoo_daily(yahoo_symbol(code), "2026-01-01", sell_date)
    except Exception as exc:
        try:
            daily_rows, daily_url = fetch_daily(secid_for_stock(code), "2026-01-01", sell_date)
            daily_provider = "Eastmoney"
        except Exception as fallback_exc:
            errors.append(f"daily: Yahoo Finance {exc}; Eastmoney {fallback_exc}")
    buy_day = daily_summary(daily_rows, buy_date)
    sell_day = daily_summary(daily_rows, sell_date)
    buy_intraday = sell_intraday = []
    buy_intraday_url = sell_intraday_url = ""
    for field, trading_date in (("buy", buy_date), ("sell", sell_date)):
        try:
            rows, url = fetch_intraday(code, trading_date)
            if field == "buy":
                buy_intraday, buy_intraday_url = rows, url
            else:
                sell_intraday, sell_intraday_url = rows, url
        except Exception as exc:
            errors.append(f"{field} intraday: {exc}")
    buy_price = number((sample.get("prices") or {}).get("buy"))
    sell_summary = intraday_summary(sell_intraday, buy_price, buy_day.get("close") if buy_day else None)
    sample["openingRegime"] = classify_opening(sell_summary)
    prices = sample.setdefault("prices", {})
    if buy_day:
        prices["buyOpen"] = buy_day.get("open")
        prices["buyClose"] = buy_day.get("close")
    if sell_summary:
        prices["nextOpen"] = sell_summary.get("open")
        prices["nextHigh"] = sell_summary.get("highBefore1000")
        prices["nextLow"] = sell_summary.get("lowBefore1000")
        prices["nextClose"] = sell_summary.get("close1000")
    sample["market"] = {
        "buyDay": market_day(index_rows, buy_date),
        "sellDay": market_day(index_rows, sell_date),
    }
    sample["webMarketEvidence"] = {
        "provider": {"daily": daily_provider, "intraday": "Yahoo Finance"},
        "fetchedAt": now_iso(),
        "buyDate": buy_date,
        "sellDate": sell_date,
        "dailyUrl": daily_url,
        "buyIntradayUrl": buy_intraday_url,
        "sellIntradayUrl": sell_intraday_url,
        "buyDay": buy_day,
        "sellDay": sell_day,
        "buyTail": intraday_summary(buy_intraday, buy_price, None),
        "sellBefore1000": sell_summary,
        "errors": errors,
    }
    missing = set(sample.get("missingEvidence") or [])
    if buy_day:
        missing.discard("buy")
        missing.discard("five_day")
    if sell_day and sell_summary:
        missing.discard("sell")
    if sample["market"]["buyDay"]:
        missing.discard("market_buy")
    if sample["market"]["sellDay"]:
        missing.discard("market_sell")
    sample["missingEvidence"] = sorted(missing)
    label = "止盈" if sample.get("outcome") == "take_profit" else "止损" if sample.get("outcome") == "stop_loss" else "待确认"
    sample["diagnosis"] = (
        f"用户确认{label}；T+1交易发生于10:00前，补录时间不作为成交时间。"
        f"买入日收盘/MA5偏离 {buy_day.get('closeVsMa5Pct') if buy_day else '--'}%，"
        f"T+1竞价缺口 {sell_summary.get('gapPct') if sell_summary else '--'}%，"
        f"10点前MFE {sell_summary.get('mfeBefore1000Pct') if sell_summary else '--'}%。"
    )
    return sample, errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch public K-line evidence for newly learned T+1 samples")
    parser.add_argument("--since", help="Only enrich samples with buyDate on or after this ISO date")
    parser.add_argument("--refresh", action="store_true", help="Refresh samples that already contain web evidence")
    args = parser.parse_args()
    source = read_json(SAMPLES_PATH)
    samples = source.get("samples") or []
    selected = [
        sample
        for sample in samples
        if (not args.since or str(sample.get("buyDate") or "") >= args.since)
        and (args.refresh or not sample.get("webMarketEvidence"))
    ]
    if not selected:
        print(json.dumps({"selected": 0, "enriched": 0, "errors": []}, ensure_ascii=False, indent=2))
        return
    first_date = min(str(sample.get("buyDate")) for sample in selected)
    last_date = max(str(sample.get("sellDate")) for sample in selected)
    index_rows = {}
    index_urls = {}
    index_providers = {}
    errors = []
    for name, secid in INDEX_SECIDS.items():
        try:
            index_rows[name], index_urls[name] = fetch_yahoo_daily(INDEX_SYMBOLS[name], "2026-01-01", last_date)
            index_providers[name] = "Yahoo Finance"
        except Exception as exc:
            try:
                index_rows[name], index_urls[name] = fetch_daily(secid, "2026-01-01", last_date)
                index_providers[name] = "Eastmoney"
            except Exception as fallback_exc:
                index_rows[name] = []
                errors.append(f"{name} index: Yahoo Finance {exc}; Eastmoney {fallback_exc}")
    evidence_samples = []
    completed = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_samples = {executor.submit(enrich_sample, sample, index_rows): sample for sample in selected}
        for future in as_completed(future_samples):
            sample = future_samples[future]
            try:
                completed.append(future.result())
            except Exception as exc:
                completed.append((sample, [f"unexpected: {exc}"]))
    for enriched, sample_errors in sorted(completed, key=lambda item: item[0].get("sampleId") or ""):
        evidence_samples.append(
            {
                "sampleId": enriched.get("sampleId"),
                "stockCode": enriched.get("stockCode"),
                "stockName": enriched.get("stockName"),
                "outcome": enriched.get("outcome"),
                "evidence": enriched.get("webMarketEvidence"),
                "market": enriched.get("market"),
            }
        )
        errors.extend(f"{enriched.get('sampleId')}: {item}" for item in sample_errors)
    source["updatedAt"] = now_iso()
    write_json(SAMPLES_PATH, source)
    evidence_path = EVIDENCE_DIR / f"{datetime.now().date().isoformat()}.json"
    write_json(
        evidence_path,
        {
            "schemaVersion": 1,
            "fetchedAt": now_iso(),
            "dateRange": {"from": first_date, "to": last_date},
            "sources": {"indexes": index_urls, "indexProviders": index_providers},
            "samples": evidence_samples,
            "errors": errors,
        },
    )
    append_event(
        {
            "evidencePath": evidence_path.relative_to(ROOT).as_posix(),
            "selected": len(selected),
            "enriched": sum(not item["evidence"].get("errors") for item in evidence_samples),
            "errorCount": len(errors),
        }
    )
    print(
        json.dumps(
            {
                "selected": len(selected),
                "evidencePath": evidence_path.relative_to(ROOT).as_posix(),
                "errors": errors,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
