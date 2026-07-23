from __future__ import annotations

import hashlib
import json
import math
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
LATEST_PATH = DATA_DIR / "latest.json"
BOARD_HISTORY_PATH = DATA_DIR / "board_history.json"
CN_TZ = timezone(timedelta(hours=8))

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
EASTMONEY_UT = "bd1d9ddb04089700cf9c27f6f7426281"
EASTMONEY_HOSTS = (
    "push2.eastmoney.com",
    "push2delay.eastmoney.com",
    "4.push2.eastmoney.com",
    "60.push2.eastmoney.com",
    "61.push2.eastmoney.com",
    "82.push2.eastmoney.com",
)

STARTED = time.monotonic()
MAX_RUNTIME_SECONDS = 210
HTTP_TIMEOUT_SECONDS = 8
MAX_BOARDS_FOR_MEMBERS = 10
MAX_MEMBERS_PER_BOARD = 50
MAX_STOCK_CANDIDATES = 90
MAX_TAIL_HISTORY_CANDIDATES = 36
MAX_RECOMMENDATIONS = 10
MAX_RECOMMENDATIONS_PER_INDUSTRY = 3
ALLOW_GROWTH_BOARDS = False
GROWTH_BOARD_PREFIXES = ("30", "68")
STRATEGY_TAIL_MAIN = "TAIL_MAIN"
STRATEGY_AM_TOP = "AM_TOP"
TAIL_STRATEGY_ID = "TAIL_T1_V31_EMPIRICAL"
AM_TOP_BUY_WINDOW = "09:26 watch; 09:31-09:38 primary entry; 09:40+ confirm only"
AM_TOP_MIN_PCT = 4.0
AM_TOP_MAX_PCT = 10.3
TAIL_BUY_WINDOW = "13:30 watch; 14:10-14:35 confirm; 14:35+ limit-up/reseal only"
TAIL_TARGET_TIME = "Next day 09:25 auction watch; 09:30-09:35 opening confirmation; exit non-limit-up remainder at 10:00."
TAIL_MIN_AMOUNT = 150_000_000
TAIL_HARD_MAX_TURNOVER = 35.0
TAIL_HARD_MAX_PULLBACK = 2.5
TAIL_PREFERRED_MAX_PULLBACK = 2.0
TAIL_MAX_PCT = 10.3
TAIL_MIN_STOCK_SCORE = 7
TAIL_MIN_BOARD_SCORE = 4
OCR_DOWNGRADE = 45
OCR_REJECT = 65
SIMPLE_EXECUTION_SCORE_MIN = 65
EXECUTION_TOLERANCE_SCORE_MIN = 60

errors: list[str] = []
source_health: dict[str, dict[str, Any]] = {}
daily_history_cache: dict[str, dict[str, Any]] = {}


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(CN_TZ)
    today = now.strftime("%Y-%m-%d")
    history = load_json(BOARD_HISTORY_PATH, {"items": []})
    previous = load_json(LATEST_PATH, {})

    boards = fetch_all_boards()
    if not boards:
        write_fallback(now, today, previous)
        update_board_history(history, today, [])
        return

    rank_map = {board["code"]: index + 1 for index, board in enumerate(boards)}
    evaluated_boards = evaluate_boards(boards, rank_map, history, now)
    qualified_boards = [board for board in evaluated_boards if board["qualified"]]
    active_strategies = active_strategy_windows(now)
    recommendation_board_pool = select_recommendation_boards(evaluated_boards)
    am_top_quotes = fetch_all_a_shares() if STRATEGY_AM_TOP in active_strategies and remaining_seconds() > 35 else []
    market_quotes = fetch_market_breadth(am_top_quotes or None) if remaining_seconds() > 35 else []
    market_monitor = build_market_monitor(market_quotes, evaluated_boards)
    recommendations = build_recommendations(recommendation_board_pool, now, am_top_quotes, market_monitor)
    no_recommendation_reason = None
    if not recommendations:
        if not active_strategies:
            no_recommendation_reason = "OUTSIDE_STRATEGY_WINDOW"
        elif market_monitor.get("riskLevel") == "RISK_OFF":
            no_recommendation_reason = "MARKET_RISK_OFF"
        else:
            no_recommendation_reason = "NO_STRICT_MATCH"
    news = fetch_news() if remaining_seconds() > 25 else []

    latest = {
        "meta": {
            "schemaVersion": 4,
            "generatedAt": now.isoformat(),
            "tradingDate": today,
            "mode": "fast-snapshot",
            "activeStrategies": sorted(active_strategies),
            "noRecommendationReason": no_recommendation_reason,
            "sourceHealth": source_list(),
            "errors": errors[:30],
            "runtimeSeconds": round(time.monotonic() - STARTED, 2),
        },
        "market": {
            "recommendationCount": len(recommendations),
            "qualifiedBoardCount": len(qualified_boards),
            "monitor": market_monitor,
        },
        "boards": strip_members(evaluated_boards[:12]),
        "recommendations": recommendations,
        "news": news or previous.get("news", [])[:8],
    }

    write_json(LATEST_PATH, latest)
    update_board_history(history, today, evaluated_boards)


def write_fallback(now: datetime, today: str, previous: dict[str, Any]) -> None:
    previous_boards = previous.get("boards", [])
    previous_recs = previous.get("recommendations", [])
    previous_news = previous.get("news", [])
    if previous_boards or previous_recs:
        mark_source(
            "Historical cache",
            True,
            "data/latest.json",
            "External sources failed; kept the last successful snapshot.",
        )

    latest = {
        "meta": {
            "schemaVersion": 4,
            "generatedAt": now.isoformat(),
            "tradingDate": today,
            "mode": "cached-fallback" if (previous_boards or previous_recs) else "no-current-data",
            "sourceHealth": source_list(previous),
            "errors": (errors or ["No usable quote rows returned this run."])[:30],
            "runtimeSeconds": round(time.monotonic() - STARTED, 2),
        },
        "market": {
            "recommendationCount": len(previous_recs),
            "qualifiedBoardCount": len(previous_boards),
            "monitor": previous.get("market", {}).get("monitor", {}),
        },
        "boards": previous_boards[:12],
        "recommendations": previous_recs[:MAX_RECOMMENDATIONS],
        "news": previous_news[:8],
    }
    write_json(LATEST_PATH, latest)


def fetch_all_boards() -> list[dict[str, Any]]:
    boards: list[dict[str, Any]] = []
    boards.extend(fetch_board_list("Industry board", "m:90+t:2"))
    boards.extend(fetch_board_list("Concept board", "m:90+t:3"))

    result = dedupe_boards(boards)
    if result:
        return result[:60]

    stocks = fetch_all_a_shares()
    if stocks:
        mark_source(
            "Eastmoney",
            True,
            "https://quote.eastmoney.com/",
            "Board endpoint unavailable; used A-share quote snapshot grouped by industry.",
        )
        errors.append("Board endpoints returned no rows; used all-A-share industry fallback.")
        return boards_from_a_shares(stocks)[:60]

    return []


def fetch_board_list(kind: str, fs: str) -> list[dict[str, Any]]:
    fields = "f12,f14,f2,f3,f4,f5,f6,f7,f8,f15,f16,f17,f18,f20,f62"
    rows = safe_clist("Eastmoney", fs, fields, page_size=240)
    result = []
    for row in rows:
        code = str(row.get("f12") or "")
        if not code.startswith("BK"):
            continue
        result.append(
            {
                "code": code,
                "name": text(row.get("f14")),
                "kind": kind,
                "price": number(row.get("f2")),
                "pct": number(row.get("f3")),
                "amount": number(row.get("f6")),
                "turnover": number(row.get("f8")),
                "open": number(row.get("f17")),
                "preClose": number(row.get("f18")),
                "mainNet": number(row.get("f62")),
            }
        )
    return result


def fetch_all_a_shares() -> list[dict[str, Any]]:
    fields = "f12,f13,f14,f2,f3,f4,f5,f6,f7,f8,f10,f15,f16,f17,f18,f20,f21,f62,f66,f100"
    fs = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
    rows = safe_clist("Eastmoney", fs, fields, page_size=5000)
    stocks = [normalize_stock_quote(row) for row in rows]
    stocks = [item for item in stocks if item.get("code") and item.get("price")]
    stocks.sort(key=lambda item: (item.get("pct") or -999, item.get("amount") or 0), reverse=True)
    return stocks


def fetch_market_breadth(top_quotes: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    fields = "f12,f13,f14,f2,f3,f4,f5,f6,f7,f8,f10,f15,f16,f17,f18,f20,f21,f62,f66,f100"
    fs = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
    top = top_quotes if top_quotes is not None else fetch_all_a_shares()
    bottom_rows = safe_clist("Eastmoney", fs, fields, page_size=100, descending=False)
    bottom = [normalize_stock_quote(row) for row in bottom_rows]
    deduped = {item.get("code"): item for item in [*top, *bottom] if item.get("code") and item.get("price")}
    return list(deduped.values())


def enrich_tail_history(quote: dict[str, Any], now: datetime) -> dict[str, Any]:
    code = quote.get("code") or ""
    if not code or remaining_seconds() < 20:
        return {**quote, "dailyMetrics": build_daily_metrics(quote, [], now)}
    rows = daily_history_cache.get(code)
    if rows is None:
        rows = fetch_daily_klines(code)
        daily_history_cache[code] = rows
    return {**quote, "dailyMetrics": build_daily_metrics(quote, rows, now)}


def fetch_daily_klines(code: str) -> list[dict[str, Any]]:
    secid = f"{1 if code.startswith('6') else 0}.{code}"
    params = {
        "secid": secid,
        "ut": EASTMONEY_UT,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "1",
        "end": "20500101",
        "lmt": "16",
    }
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get?" + parse.urlencode(params)
    try:
        payload = json.loads(fetch_bytes("Eastmoney", url, referer="https://quote.eastmoney.com/").decode("utf-8", "ignore"))
        lines = payload.get("data", {}).get("klines") or []
        result = []
        for line in lines:
            parts = line.split(",")
            if len(parts) < 11:
                continue
            result.append(
                {
                    "date": parts[0],
                    "open": number(parts[1]),
                    "close": number(parts[2]),
                    "high": number(parts[3]),
                    "low": number(parts[4]),
                    "volume": number(parts[5]),
                    "amount": number(parts[6]),
                    "amplitude": number(parts[7]),
                    "pct": number(parts[8]),
                    "turnover": number(parts[10]),
                }
            )
        if result:
            mark_source("Eastmoney", True, url, "Quote snapshot and daily K-line history OK")
        return result
    except Exception as exc:
        errors.append(f"Eastmoney daily K skipped for {code}: {short_error(exc)}")
        return []


def build_daily_metrics(
    quote: dict[str, Any],
    rows: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    today = now.strftime("%Y-%m-%d")
    completed = [row for row in rows if row.get("date") and row["date"] < today and row.get("close")]
    completed = completed[-15:]
    closes = [row["close"] for row in completed]
    amounts = [row.get("amount") or 0 for row in completed[-5:] if (row.get("amount") or 0) > 0]
    current_price = quote.get("price") or 0
    current_amount = project_amount_to_close(quote.get("amount") or 0, now)
    amount_ma5 = sum(amounts) / len(amounts) if amounts else None
    amount_ratio = current_amount / amount_ma5 if amount_ma5 else None
    ma5_values = closes[-4:] + ([current_price] if current_price else [])
    ma10_values = closes[-9:] + ([current_price] if current_price else [])
    ma5 = sum(ma5_values) / len(ma5_values) if ma5_values else None
    ma10 = sum(ma10_values) / len(ma10_values) if ma10_values else None
    previous_ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else None
    earlier_ma5 = sum(closes[-6:-1]) / 5 if len(closes) >= 6 else None
    deviation_ma5 = ((current_price / ma5) - 1) * 100 if current_price and ma5 else None
    gain5d = ((current_price / closes[-5]) - 1) * 100 if current_price and len(closes) >= 5 else None
    gain10d = ((current_price / closes[-10]) - 1) * 100 if current_price and len(closes) >= 10 else None
    breakout_level = max(closes[-5:]) if closes else None
    close_above_breakout = (
        current_price >= breakout_level * 0.995
        if current_price and breakout_level
        else None
    )
    ma5_rising = ma5 >= previous_ma5 if ma5 is not None and previous_ma5 is not None else None
    prior_ma5_rising = previous_ma5 >= earlier_ma5 if previous_ma5 is not None and earlier_ma5 is not None else None
    previous_close_above_ma5 = (
        closes[-1] >= previous_ma5 * 0.99
        if closes and previous_ma5
        else None
    )
    ma5_above_ma10 = ma5 >= ma10 * 0.99 if ma5 is not None and ma10 is not None else None
    first_pullback_proxy = bool(
        current_price
        and ma5
        and current_price >= ma5 * 0.99
        and (amount_ratio is None or amount_ratio <= 1.60)
        and 2.5 <= (quote.get("pct") or 0) <= 6.5
        and ma5_rising is not False
    )
    return {
        "historyAvailable": len(completed) >= 5,
        "sampleCount": len(completed),
        "amountMA5": round2(amount_ma5),
        "projectedAmount": round2(current_amount),
        "amountRatio": round2(amount_ratio),
        "ma5": round2(ma5),
        "ma10": round2(ma10),
        "ma5Rising": ma5_rising,
        "priorMA5Rising": prior_ma5_rising,
        "previousCloseAboveMA5": previous_close_above_ma5,
        "ma5AboveMA10": ma5_above_ma10,
        "trendPersistence": trend_persistence_ok(
            {
                "priorMA5Rising": prior_ma5_rising,
                "previousCloseAboveMA5": previous_close_above_ma5,
                "ma5AboveMA10": ma5_above_ma10,
            }
        ),
        "deviationMA5Pct": round2(deviation_ma5),
        "gain5dPct": round2(gain5d),
        "gain10dPct": round2(gain10d),
        "prevDayReturn": round2(completed[-1].get("pct")) if completed else None,
        "breakoutLevel": round2(breakout_level),
        "closeAboveBreakout": close_above_breakout,
        "firstPullbackProxy": first_pullback_proxy,
        "surgeCount5d": sum(1 for row in completed[-5:] if (row.get("pct") or 0) >= 5),
    }


def trading_minutes_elapsed(now: datetime) -> int:
    minute = now.hour * 60 + now.minute
    if minute < 9 * 60 + 30:
        return 0
    if minute <= 11 * 60 + 30:
        return max(1, minute - (9 * 60 + 30))
    if minute < 13 * 60:
        return 120
    if minute <= 15 * 60:
        return min(240, 120 + minute - 13 * 60)
    return 240


def project_amount_to_close(amount: float, now: datetime) -> float:
    elapsed = trading_minutes_elapsed(now)
    if elapsed <= 0 or elapsed >= 240:
        return amount
    return amount * min(2.0, 240 / max(30, elapsed))


def build_market_monitor(stocks: list[dict[str, Any]], boards: list[dict[str, Any]]) -> dict[str, Any]:
    if not stocks:
        hot_boards = sum(1 for board in boards[:12] if (board.get("passed") or 0) >= 4)
        score = 50 + min(25, hot_boards * 4)
        market_gate_score = min(5, hot_boards)
        return {
            "emotionScore": clamp(score, 0, 100),
            "marketGateScore": market_gate_score,
            "marketGatePassed": market_gate_score >= 3,
            "hardVeto": False,
            "riskLevel": "NORMAL" if score >= 60 and market_gate_score >= 3 else "CAUTION",
            "limitUpCount": None,
            "limitDownCount": None,
            "brokenBoardRate": None,
            "note": "Market monitor fell back to board strength.",
        }

    limit_up_count = sum(1 for item in stocks if is_limit_up(item))
    limit_down_count = sum(1 for item in stocks if is_limit_down(item))
    big_down_count = sum(1 for item in stocks if (item.get("pct") or 0) <= -7)
    limit_touch_count = sum(1 for item in stocks if touched_limit_up(item))
    broken_count = sum(1 for item in stocks if touched_limit_up(item) and not is_limit_up(item))
    broken_rate = broken_count / limit_touch_count if limit_touch_count else 0
    top_board_pct = boards[0].get("pct") if boards else 0

    market_checks = [
        limit_up_count >= 30,
        limit_down_count <= 10 and big_down_count <= 35,
        broken_rate <= 0.40,
        limit_up_count >= 18 and (top_board_pct or 0) >= 1.0,
        (top_board_pct or 0) >= 0 and big_down_count <= 50,
    ]
    market_gate_score = sum(market_checks)
    hard_veto = broken_rate > 0.50 or limit_down_count >= 25 or big_down_count >= 70

    score = 50
    if limit_up_count >= 30:
        score += 15
    elif limit_up_count >= 18:
        score += 8
    else:
        score -= 8
    if limit_down_count <= 10:
        score += 10
    elif limit_down_count >= 25:
        score -= 12
    if broken_rate <= 0.35:
        score += 15
    elif broken_rate >= 0.50:
        score -= 15
    if big_down_count <= 20:
        score += 8
    elif big_down_count >= 50:
        score -= 12
    if (top_board_pct or 0) >= 1.2:
        score += 8
    elif (top_board_pct or 0) < 0:
        score -= 8
    score = round(clamp(score, 0, 100), 1)
    if hard_veto or market_gate_score < 3:
        risk_level = "RISK_OFF"
    else:
        risk_level = "NORMAL" if score >= 60 else "CAUTION"
    return {
        "emotionScore": score,
        "marketGateScore": market_gate_score,
        "marketGatePassed": market_gate_score >= 3 and not hard_veto,
        "hardVeto": hard_veto,
        "riskLevel": risk_level,
        "limitUpCount": limit_up_count,
        "limitDownCount": limit_down_count,
        "bigDownCount": big_down_count,
        "limitTouchCount": limit_touch_count,
        "brokenBoardCount": broken_count,
        "brokenBoardRate": round(broken_rate, 3),
        "breadthSampleSize": len(stocks),
        "breadthMethod": "top-100 plus bottom-100 movers",
        "topBoardPct": round2(top_board_pct or 0),
        "note": "RISK_OFF blocks new buys; CAUTION keeps only high-edge candidates.",
    }


def boards_from_a_shares(stocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for stock in stocks:
        industry = stock.get("industry") or "Unclassified"
        grouped.setdefault(industry, []).append(stock)

    boards = []
    for name, members in grouped.items():
        tradable = [item for item in members if item.get("pct") is not None]
        if len(tradable) < 3:
            continue
        amount = sum(item.get("amount") or 0 for item in tradable)
        pct = weighted_average(tradable, "pct", "amount")
        turnover = weighted_average(tradable, "turnover", "amount")
        main_net = sum(item.get("mainNet") or 0 for item in tradable)
        code = "IND_" + hashlib.md5(name.encode("utf-8")).hexdigest()[:8]
        tradable.sort(key=lambda item: (item.get("pct") or -999, item.get("amount") or 0), reverse=True)
        boards.append(
            {
                "code": code,
                "name": name,
                "kind": "Industry fallback",
                "price": None,
                "pct": pct,
                "amount": amount,
                "turnover": turnover,
                "open": None,
                "preClose": None,
                "mainNet": main_net,
                "members": tradable[:MAX_MEMBERS_PER_BOARD],
            }
        )
    boards.sort(key=lambda item: (item.get("pct") or -999, item.get("amount") or 0), reverse=True)
    return boards


def evaluate_boards(
    boards: list[dict[str, Any]],
    rank_map: dict[str, int],
    history: dict[str, Any],
    now: datetime,
) -> list[dict[str, Any]]:
    evaluated = []
    for board in boards[:MAX_BOARDS_FOR_MEMBERS]:
        if deadline_hit():
            errors.append("Runtime budget reached while evaluating boards.")
            break
        members = board.get("members") or fetch_board_members(board["code"])
        for index, member in enumerate(members):
            member["boardFrontPct"] = (index + 1) / max(1, len(members))
        limit_up_count = sum(1 for item in members if is_limit_up(item))
        big_up_count = sum(1 for item in members if (item.get("pct") or 0) >= 5)
        leader_ok = limit_up_count >= 2 or (
            any((item.get("pct") or 0) >= 7 for item in members[:8]) and big_up_count >= 3
        )
        continuous_ok = board_continuous_ok(board["code"], rank_map, history, now.strftime("%Y-%m-%d"))
        rank = rank_map.get(board["code"], 99)
        amount_ok = (board.get("amount") or 0) >= 8_000_000_000
        amount_ratio = board_amount_ratio(board, history, now)
        amount_expansion_ok = amount_ratio is None and amount_ok or (amount_ratio or 0) >= 1.30
        position_proxy_ok = rank <= 15 and (board.get("pct") or 0) >= 1.0

        criteria = [
            ("[SectorGate] Two-day top-10 or three-day top-20 continuity", continuous_ok),
            ("[SectorGate] Tail rank remains top-15 positive", position_proxy_ok),
            ("[SectorGate] Limit-up ladder or 5%+ cohort exists", limit_up_count >= 2 or big_up_count >= 5),
            ("[SectorGate] Board amount expands at least 1.30x", amount_expansion_ok),
            ("[SectorGate] Leaders have follow-through support", leader_ok),
        ]
        passed_labels = [label for label, ok in criteria if ok]
        passed = len(passed_labels)
        score = round((passed / 5) * 82 + max(0, 18 - rank * 0.35), 2)

        evaluated.append(
            {
                **board,
                "rank": rank,
                "passed": passed,
                "qualified": passed >= 4,
                "score": min(100, score),
                "criteria": passed_labels,
                "continuous": continuous_ok,
                "amountRatio": round2(amount_ratio),
                "limitUpCount": limit_up_count,
                "bigUpCount": big_up_count,
                "members": members[:30],
            }
        )

    for board in boards[MAX_BOARDS_FOR_MEMBERS:12]:
        rank = rank_map.get(board["code"], 99)
        evaluated.append(
            {
                **board,
                "rank": rank,
                "passed": 2 if rank <= 12 else 1,
                "qualified": False,
                "score": max(0, 48 - rank),
                "criteria": ["Board is near the top of today's movers"],
                "limitUpCount": 0,
                "bigUpCount": 0,
                "members": [],
            }
        )

    evaluated.sort(key=lambda item: (item["qualified"], item["score"], item.get("pct") or 0), reverse=True)
    return evaluated


def select_recommendation_boards(boards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = [
        board
        for board in boards
        if board.get("qualified")
        or (
            (board.get("passed") or 0) >= 3
            and (board.get("rank") or 99) <= 15
            and (board.get("pct") or 0) >= 1.2
            and ((board.get("limitUpCount") or 0) >= 1 or (board.get("bigUpCount") or 0) >= 4)
        )
    ]
    return selected[:MAX_BOARDS_FOR_MEMBERS]


def build_recommendations(
    qualified_boards: list[dict[str, Any]],
    now: datetime | None = None,
    am_top_quotes: list[dict[str, Any]] | None = None,
    market_monitor: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    snapshot_now = now or datetime.now(CN_TZ)
    active_strategies = active_strategy_windows(snapshot_now)
    if market_monitor and market_monitor.get("riskLevel") == "RISK_OFF":
        errors.append("Market monitor is RISK_OFF; no new buy recommendation generated.")
        return []
    seen: set[str] = set()
    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for board in qualified_boards[:MAX_BOARDS_FOR_MEMBERS]:
        for member in board.get("members", []):
            code = member.get("code")
            if not code or code in seen:
                continue
            seen.add(code)
            if stock_prefilter(member, active_strategies, snapshot_now):
                candidates.append((member, board))
    if STRATEGY_AM_TOP in active_strategies:
        for quote in am_top_quotes or []:
            code = quote.get("code")
            if not code or code in seen:
                continue
            seen.add(code)
            if morning_top_prefilter(quote, snapshot_now):
                candidates.append((quote, am_top_board_for_quote(quote)))

    candidates.sort(
        key=lambda pair: (
            pre_rank_candidate(pair[0], pair[1], active_strategies),
            pair[1].get("score") or 0,
            pair[0].get("amount") or 0,
        ),
        reverse=True,
    )

    recommendations = []
    candidate_limit = (
        MAX_TAIL_HISTORY_CANDIDATES
        if STRATEGY_TAIL_MAIN in active_strategies
        else MAX_STOCK_CANDIDATES
    )
    for quote, board in candidates[:candidate_limit]:
        if STRATEGY_TAIL_MAIN in active_strategies:
            quote = enrich_tail_history(quote, snapshot_now)
        item = evaluate_stock_snapshot(quote, board, active_strategies, snapshot_now, market_monitor)
        if item:
            recommendations.append(item)
    recommendations.sort(
        key=lambda item: (
            item.get("finalScore") or item.get("t1EdgeScore") or 0,
            item.get("expectedReturnPct") or 0,
            item.get("winRate") or item.get("confidence") or 0,
            item.get("board", {}).get("score") or 0,
        ),
        reverse=True,
    )
    recommendations = diversify_recommendations(recommendations)
    if market_monitor and market_monitor.get("riskLevel") == "CAUTION":
        recommendations = [
            item
            for item in recommendations
            if item.get("strategyTag") == STRATEGY_AM_TOP
            or (
                item.get("candidateStatus") == "STRONG_CANDIDATE"
                and (item.get("riskPct") or 99) <= 4.2
            )
        ]
    recommendations = recommendations[:MAX_RECOMMENDATIONS]

    for index, item in enumerate(recommendations, start=1):
        item["rank"] = index
    return recommendations


def diversify_recommendations(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    counts: dict[str, int] = {}

    for item in items:
        key = recommendation_industry_key(item)
        if counts.get(key, 0) < MAX_RECOMMENDATIONS_PER_INDUSTRY:
            selected.append(item)
            counts[key] = counts.get(key, 0) + 1
        if len(selected) >= MAX_RECOMMENDATIONS:
            return selected
    return selected


def recommendation_industry_key(item: dict[str, Any]) -> str:
    return text(item.get("industry") or item.get("board", {}).get("name") or item.get("code") or "Unknown")


def am_top_board_for_quote(quote: dict[str, Any]) -> dict[str, Any]:
    industry = quote.get("industry") or "AM_TOP market scan"
    return {
        "code": "AM_TOP_" + hashlib.md5(industry.encode("utf-8")).hexdigest()[:8],
        "name": industry,
        "passed": 4,
        "qualified": True,
        "score": 82,
        "criteria": ["AM_TOP all-main-board scan", "Morning top candidate is evaluated by stock shape"],
        "limitUpCount": 0,
        "bigUpCount": 0,
    }


def high_to_close_pullback_pct(quote: dict[str, Any]) -> float:
    price = quote.get("price") or 0
    high = quote.get("high") or price
    if not price or not high:
        return 99.0
    return max(0.0, ((high - price) / high) * 100)


def upper_shadow_ratio(quote: dict[str, Any]) -> float:
    price = quote.get("price") or 0
    open_price = quote.get("open") or price
    pre_close = quote.get("preClose") or price
    high = quote.get("high") or price
    if not price or not open_price or not high:
        return 0.0
    body = abs(price - open_price)
    upper_shadow = max(0.0, high - max(price, open_price))
    min_body = max((pre_close or price) * 0.002, 0.01)
    return upper_shadow / max(body, min_body)


def quote_amplitude_pct(quote: dict[str, Any]) -> float:
    amplitude = quote.get("amplitude")
    if amplitude is not None:
        return amplitude
    high = quote.get("high") or 0
    low = quote.get("low") or 0
    pre_close = quote.get("preClose") or 0
    return ((high - low) / pre_close) * 100 if high and low and pre_close else 0


def is_stable_limit_up_proxy(quote: dict[str, Any]) -> bool:
    return (
        is_limit_up(quote)
        and high_to_close_pullback_pct(quote) <= 0.35
        and intraday_position(quote) >= 0.96
    )


def trend_persistence_ok(metrics: dict[str, Any]) -> bool:
    flags = [
        metrics.get("priorMA5Rising"),
        metrics.get("previousCloseAboveMA5"),
        metrics.get("ma5AboveMA10"),
    ]
    known = [flag for flag in flags if flag is not None]
    return len(known) < 2 or sum(flag is True for flag in known) >= 2


def estimate_overnight_crowding_score(quote: dict[str, Any]) -> float:
    metrics = quote.get("dailyMetrics") or {}
    pct = quote.get("pct") or 0
    turnover = quote.get("turnover") or 0
    amount_ratio = metrics.get("amountRatio")
    amplitude = quote_amplitude_pct(quote)
    pullback = high_to_close_pullback_pct(quote)
    score = 5.0
    if (metrics.get("prevDayReturn") or 0) <= -7 and pct >= 7:
        score += 30
    if (metrics.get("gain5dPct") or 0) >= 25:
        score += 22
    if (metrics.get("gain10dPct") or 0) >= 40:
        score += 24
    if amplitude > 10 and not is_stable_limit_up_proxy(quote):
        score += 28
    elif amplitude > 8:
        score += 12
    if turnover > 25 and not is_stable_limit_up_proxy(quote):
        score += 18
    if amount_ratio is not None and amount_ratio >= 2.2:
        score += 12
    if pullback > 2.0:
        score += 12
    if (metrics.get("surgeCount5d") or 0) >= 2:
        score += 16
    if metrics.get("historyAvailable") and not trend_persistence_ok(metrics):
        score += 22
    return round2(clamp(score, 0, 100)) or 0


def estimate_execution_tolerance_score(quote: dict[str, Any]) -> float:
    metrics = quote.get("dailyMetrics") or {}
    price = quote.get("price") or 0
    avg_price = quote.get("avgPrice") or average_price(quote.get("amount"), quote.get("volume")) or price
    price_vs_avg = ((price / avg_price) - 1) * 100 if price and avg_price else 0
    deviation = metrics.get("deviationMA5Pct")
    amount_ratio = metrics.get("amountRatio")
    score = 100.0
    score -= max(0, quote_amplitude_pct(quote) - 6.5) * 5
    score -= max(0, (quote.get("turnover") or 0) - 18) * 1.2
    score -= max(0, high_to_close_pullback_pct(quote) - 1.2) * 8
    score -= max(0, 0.72 - intraday_position(quote)) * 80
    score -= max(0, -price_vs_avg) * 10
    if deviation is not None:
        score -= max(0, deviation - 10) * 3
    else:
        score -= 5
    if amount_ratio is not None and amount_ratio > 2.8:
        score -= (amount_ratio - 2.8) * 12
    if metrics.get("historyAvailable") and not trend_persistence_ok(metrics):
        score -= 18
    return round2(clamp(score, 0, 100)) or 0


def estimate_simple_execution_score(quote: dict[str, Any], tolerance_score: float) -> float:
    metrics = quote.get("dailyMetrics") or {}
    price = quote.get("price") or 0
    avg_price = quote.get("avgPrice") or average_price(quote.get("amount"), quote.get("volume")) or price
    price_vs_avg = ((price / avg_price) - 1) * 100 if price and avg_price else 0
    score = (
        tolerance_score * 0.55
        + intraday_position(quote) * 20
        + clamp(100 - high_to_close_pullback_pct(quote) * 20, 0, 100) * 0.15
        + (10 if price_vs_avg >= 0 else 0)
    )
    if metrics.get("ma5Rising") is False:
        score -= 12
    return round2(clamp(score, 0, 100)) or 0


def estimate_recovery_proxy_score(quote: dict[str, Any]) -> float:
    metrics = quote.get("dailyMetrics") or {}
    score = 50.0
    if intraday_position(quote) >= 0.75:
        score += 15
    if high_to_close_pullback_pct(quote) <= 1.5:
        score += 10
    if metrics.get("ma5Rising"):
        score += 10
    if (metrics.get("deviationMA5Pct") or 0) <= 10:
        score += 10
    if quote_amplitude_pct(quote) > 10:
        score -= 20
    return round2(clamp(score, 0, 100)) or 0


def tail_sector_gate_ok(board: dict[str, Any]) -> bool:
    rank = board.get("rank") or 99
    passed = board.get("passed") or 0
    limit_up_count = board.get("limitUpCount") or 0
    big_up_count = board.get("bigUpCount") or 0
    return passed >= TAIL_MIN_BOARD_SCORE or (rank <= 10 and (limit_up_count >= 2 or big_up_count >= 5))


def tail_hard_veto_reasons(
    quote: dict[str, Any],
    board: dict[str, Any],
    now: datetime | None = None,
) -> list[str]:
    price = quote.get("price") or 0
    open_price = quote.get("open") or price
    amount = quote.get("amount") or 0
    pct = quote.get("pct") or 0
    turnover = quote.get("turnover") or 0
    avg_price = quote.get("avgPrice") or average_price(amount, quote.get("volume")) or price
    range_position = intraday_position(quote)
    pullback = high_to_close_pullback_pct(quote)
    shadow_ratio = upper_shadow_ratio(quote)
    amplitude = quote_amplitude_pct(quote)
    price_vs_avg = ((price / avg_price) - 1) * 100 if price and avg_price else -99
    open_to_price = ((price / open_price) - 1) * 100 if price and open_price else -99
    metrics = quote.get("dailyMetrics") or {}
    amount_ratio = metrics.get("amountRatio")
    deviation_ma5 = metrics.get("deviationMA5Pct")
    crowding_score = estimate_overnight_crowding_score(quote)
    tolerance_score = estimate_execution_tolerance_score(quote)
    simple_execution_score = estimate_simple_execution_score(quote, tolerance_score)
    stable_limit = is_stable_limit_up_proxy(quote)

    reasons: list[str] = []
    if not tail_sector_gate_ok(board):
        reasons.append("SectorGate fails: board lacks front-row ladder or continuity")
    if pct < 2.5:
        reasons.append("No valid mid-trend tail signal: gain is below 2.5%")
    if pct > TAIL_MAX_PCT:
        reasons.append("Gain exceeds the main-board strategy range")
    if turnover > TAIL_HARD_MAX_TURNOVER:
        reasons.append("HV3: turnover exceeds 35%")
    if amount < TAIL_MIN_AMOUNT:
        reasons.append("Liquidity is too thin for next-morning exit")
    if pullback > TAIL_HARD_MAX_PULLBACK:
        reasons.append("High-to-close pullback exceeds 2.5%")
    if shadow_ratio >= 1.4 and pullback > TAIL_PREFERRED_MAX_PULLBACK:
        reasons.append("Long upper shadow suggests tail distribution")
    if price_vs_avg < -0.2:
        reasons.append("Price has fallen below VWAP")
    if range_position < 0.60:
        reasons.append("Close position is below the stable tail platform")
    if open_to_price < 0 and price_vs_avg < 0:
        reasons.append("Intraday structure is weakening into the close")
    if amplitude > 10 and not stable_limit:
        reasons.append("HV2: amplitude exceeds 10% without a stable limit-up")
    if (
        (metrics.get("prevDayReturn") or 0) <= -7
        and pct >= 7
        and amplitude >= 10
        and not stable_limit
    ):
        reasons.append("HV1: high-amplitude rebound after a sharp prior-day loss")
    if deviation_ma5 is not None and deviation_ma5 > 18:
        reasons.append("MA5 deviation exceeds 18%")
    if metrics.get("historyAvailable") and not trend_persistence_ok(metrics):
        reasons.append("HV10: prior trend is not established; reject a one-day rebound")
    if (
        amount_ratio is not None
        and amount_ratio >= 3.0
        and pct < 4.0
    ):
        reasons.append("Volume exceeds 3x without enough price progress")
    if (
        amount_ratio is not None
        and amount_ratio >= 2.2
        and ((metrics.get("gain5dPct") or 0) >= 25 or (metrics.get("gain10dPct") or 0) >= 40)
    ):
        reasons.append("HV6: high-position crowding with another volume expansion")
    if crowding_score >= OCR_REJECT and not stable_limit:
        reasons.append("CrowdingGate rejects OCR >= 65")
    if tolerance_score < EXECUTION_TOLERANCE_SCORE_MIN:
        reasons.append("SimpleExecutionGate rejects low opening tolerance")
    if simple_execution_score < SIMPLE_EXECUTION_SCORE_MIN:
        reasons.append("HV9: fixed-node execution score is below 65")
    snapshot_now = now or datetime.now(CN_TZ)
    if snapshot_now.hour == 14 and snapshot_now.minute >= 40 and not stable_limit:
        reasons.append("HV5: after 14:40 only a stable limit-up/reseal is eligible")
    return reasons


def morning_minutes_after_open(now: datetime | None = None) -> int:
    snapshot_now = now or datetime.now(CN_TZ)
    minute = snapshot_now.hour * 60 + snapshot_now.minute
    return max(0, minute - (9 * 60 + 30))


def morning_min_amount(now: datetime | None = None) -> float:
    elapsed = morning_minutes_after_open(now)
    if elapsed <= 0:
        return 8_000_000
    return min(60_000_000, 8_000_000 + elapsed * 3_000_000)


def morning_min_turnover(now: datetime | None = None) -> float:
    elapsed = morning_minutes_after_open(now)
    return min(1.2, 0.10 + elapsed * 0.04)


def morning_volume_ratio_ok(volume_ratio: float | None, upper: float = 7.0) -> bool:
    if volume_ratio is None or volume_ratio <= 0:
        return True
    return 0.15 <= volume_ratio <= upper


def morning_top_hard_veto_reasons(
    quote: dict[str, Any],
    now: datetime | None = None,
) -> list[str]:
    price = quote.get("price") or 0
    amount = quote.get("amount") or 0
    avg_price = quote.get("avgPrice") or average_price(amount, quote.get("volume")) or price
    pct = quote.get("pct") or 0
    turnover = quote.get("turnover") or 0
    volume_ratio = quote.get("volumeRatio")
    range_position = intraday_position(quote)
    pullback = high_to_close_pullback_pct(quote)
    price_vs_avg = ((price / avg_price) - 1) * 100 if price and avg_price else -99
    reasons: list[str] = []
    if pct < AM_TOP_MIN_PCT or pct > AM_TOP_MAX_PCT:
        reasons.append("Morning acceleration gain zone is not matched")
    if turnover > TAIL_HARD_MAX_TURNOVER:
        reasons.append("Morning top turnover is overheated")
    if volume_ratio is not None and volume_ratio > 7.0:
        reasons.append("Morning top volume is close to exhaustion")
    if amount < morning_min_amount(now):
        reasons.append("Morning top liquidity is insufficient")
    if pullback > 3.0:
        reasons.append("Morning top has already faded from the high platform")
    if range_position < 0.72:
        reasons.append("Morning price is not holding the high platform")
    if price_vs_avg < -0.2:
        reasons.append("Morning top cannot hold above VWAP")
    snapshot_now = now or datetime.now(CN_TZ)
    minute_of_day = snapshot_now.hour * 60 + snapshot_now.minute
    if minute_of_day > 9 * 60 + 45:
        reasons.append("Morning entry window has ended after 09:45")
    elif minute_of_day >= 9 * 60 + 40 and is_limit_up(quote):
        reasons.append("Do not chase an already locked board after 09:40")
    return reasons


def evaluate_stock_snapshot(
    quote: dict[str, Any],
    board: dict[str, Any],
    active_strategies: set[str] | None = None,
    now: datetime | None = None,
    market_monitor: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if active_strategies is None:
        active_strategies = {STRATEGY_TAIL_MAIN, STRATEGY_AM_TOP}
    price = quote.get("price")
    pre_close = quote.get("preClose")
    open_price = quote.get("open") or price
    if not price or not pre_close:
        return None
    if not stock_universe_allowed(quote.get("code") or ""):
        return None

    pct = quote.get("pct") or 0
    if STRATEGY_AM_TOP in active_strategies and is_morning_top_setup(quote, board, now):
        return evaluate_morning_top_snapshot(quote, board, now)
    if STRATEGY_TAIL_MAIN not in active_strategies:
        return None

    turnover = quote.get("turnover") or 0
    main_net = quote.get("mainNet") or 0
    super_net = quote.get("superNet") or 0
    amount = quote.get("amount") or 0
    range_position = intraday_position(quote)
    high = quote.get("high") or price
    low = quote.get("low") or price
    avg_price = quote.get("avgPrice") or average_price(amount, quote.get("volume")) or price
    close_to_high = price / high if high else 0
    price_vs_avg = ((price / avg_price) - 1) * 100 if avg_price else 0
    open_to_price = ((price / open_price) - 1) * 100 if open_price else 0
    pullback = high_to_close_pullback_pct(quote)
    shadow_ratio = upper_shadow_ratio(quote)
    metrics = quote.get("dailyMetrics") or {}
    amount_ratio = metrics.get("amountRatio")
    deviation_ma5 = metrics.get("deviationMA5Pct")
    crowding_score = estimate_overnight_crowding_score(quote)
    tolerance_score = estimate_execution_tolerance_score(quote)
    simple_execution_score = estimate_simple_execution_score(quote, tolerance_score)
    recovery_score = estimate_recovery_proxy_score(quote)
    veto_reasons = tail_hard_veto_reasons(quote, board, now)
    if veto_reasons:
        return None

    stock_criteria = [
        ("[StockGate] Amount ratio is controlled", amount_ratio is None or 1.20 <= amount_ratio <= 2.80 or is_stable_limit_up_proxy(quote)),
        ("[StockGate] MA5 is rising", metrics.get("ma5Rising") is not False),
        ("[StockGate] Prior trend was established before today's surge", trend_persistence_ok(metrics)),
        ("[StockGate] MA5 deviation stays below 15%", deviation_ma5 is None or deviation_ma5 <= 15),
        ("[StockGate] Mid-stage gain is not crowded", (metrics.get("gain5dPct") or 0) < 25 and (metrics.get("gain10dPct") or 0) < 40),
        ("[StockGate] Breakout/reclaim structure remains valid", metrics.get("closeAboveBreakout") is not False or metrics.get("firstPullbackProxy") is True),
        ("[StockGate] Main/super capital is not both negative", main_net > 0 or super_net > 0),
        ("[StockGate] Turnover fits trend or strong-close type", 4.0 <= turnover <= 25.0 or is_stable_limit_up_proxy(quote)),
        ("[StockGate] Close position is at least 0.70", range_position >= 0.70),
        ("[StockGate] High-to-close pullback is at most 2.5%", pullback <= 2.5 and close_to_high >= 0.975),
        ("[StockGate] Price holds VWAP", price_vs_avg >= 0.0),
        ("[StockGate] Stock is in the board front 20%", (quote.get("boardFrontPct") or 1) <= 0.20),
        ("[StockGate] Deal amount supports next-morning exit", amount >= TAIL_MIN_AMOUNT),
    ]
    stock_labels = [label for label, ok in stock_criteria if ok]
    if len(stock_labels) < TAIL_MIN_STOCK_SCORE:
        return None

    buy_plan = choose_buy_plan_snapshot(quote, now)
    if not buy_plan:
        return None

    tail_criteria = [
        ("[TailGate] A valid v3.1 signal is present", bool(buy_plan)),
        ("[TailGate] Close holds above VWAP", price_vs_avg >= 0.0),
        ("[TailGate] Close position stays at least 0.70", range_position >= 0.70),
        ("[TailGate] Pullback from high is at most 2.5%", pullback <= 2.5),
        ("[TailGate] No distribution upper shadow", shadow_ratio < 1.4 or pullback <= 1.5),
        ("[TailGate] Capital or price spread confirms support", main_net > 0 or super_net > 0 or open_to_price >= 1.0),
        ("[TailGate] Fixed-node execution tolerance passes", tolerance_score >= EXECUTION_TOLERANCE_SCORE_MIN),
    ]
    tail_labels = [label for label, ok in tail_criteria if ok]
    if len(tail_labels) < 5:
        return None

    market_value = (market_monitor or {}).get("emotionScore")
    market_norm = clamp(float(market_value if market_value is not None else 60), 0, 100)
    sector_norm = clamp(board.get("score") or 0, 0, 100)
    stock_norm = (len(stock_labels) / len(stock_criteria)) * 100
    tail_norm = (len(tail_labels) / len(tail_criteria)) * 100
    final_score = round2(
        market_norm * 0.10
        + sector_norm * 0.20
        + stock_norm * 0.30
        + tail_norm * 0.20
        + (100 - crowding_score) * 0.05
        + simple_execution_score * 0.10
        + recovery_score * 0.05
    ) or 0
    candidate_status = (
        "STRONG_CANDIDATE"
        if final_score >= 84
        else "NORMAL_CANDIDATE"
        if final_score >= 74
        else "OBSERVE"
        if final_score >= 64
        else "REJECT"
    )
    if candidate_status not in ("STRONG_CANDIDATE", "NORMAL_CANDIDATE"):
        return None
    initial_plan = (
        "PLAN_T"
        if candidate_status == "STRONG_CANDIDATE"
        and crowding_score < OCR_DOWNGRADE
        and tolerance_score >= 70
        and (market_monitor or {}).get("riskLevel", "NORMAL") == "NORMAL"
        else "PLAN_S"
    )

    entry = buy_plan["priceRange"][0]
    stop_loss = estimate_stop_snapshot(entry, quote)
    target = estimate_target_snapshot(
        entry,
        price,
        pre_close,
        quote,
        board,
        buy_plan,
        final_score,
        initial_plan,
    )
    expected_return = ((target["targetPrice"] / entry) - 1) * 100 if entry else 0
    risk_pct = ((entry / stop_loss) - 1) * 100 if stop_loss else 0
    t1_edge_score = final_score

    return {
        "rank": None,
        "code": quote["code"],
        "name": quote["name"],
        "market": quote.get("market"),
        "price": round2(price),
        "pct": pct,
        "amount": quote.get("amount"),
        "turnover": turnover,
        "industry": quote.get("industry") or board.get("name"),
        "confidence": final_score,
        "winRate": final_score,
        "strategyTag": STRATEGY_TAIL_MAIN,
        "strategyId": TAIL_STRATEGY_ID,
        "candidateStatus": candidate_status,
        "finalScore": final_score,
        "t1EdgeScore": t1_edge_score,
        "expectedReturnPct": round2(expected_return),
        "riskPct": round2(risk_pct),
        "signalType": buy_plan.get("signalType"),
        "overnightCrowdingScore": crowding_score,
        "executionToleranceScore": tolerance_score,
        "simpleExecutionScore": simple_execution_score,
        "recoveryAfter0935Score": recovery_score,
        "initialPlan": initial_plan,
        "nextDayPlan": next_day_plan(initial_plan),
        "board": {
            "code": board["code"],
            "name": board["name"],
            "passed": board.get("passed"),
            "score": board.get("score"),
        },
        "criteria": {
            "board": board.get("criteria", []),
            "stock": [f"[{TAIL_STRATEGY_ID}] Mid-trend tail setup", *stock_labels, *tail_labels],
        },
        "buyPlan": buy_plan,
        "sellPlan": {
            "targetPrice": target["targetPrice"],
            "targetTime": target["targetTime"],
            "strategy": target["strategy"],
            "takeProfit": target["targetPrice"],
            "timeWindow": target["targetTime"],
        },
        "stopPlan": {
            "stopLoss": stop_loss,
            "rules": [
                "09:25 auction only sets the opening bias; do not sell mechanically before the open",
                "09:30-09:35 confirm follow-through: strong repair may override the overnight defensive plan",
                "09:35 classify WEAK/NEUTRAL/STRONG; WEAK sells all remainder",
                "10:00 sell every non-limit-up remainder; never widen the stop",
            ],
        },
        "sourceLinks": stock_source_links(quote["code"]),
        "sparkline": [],
    }


def evaluate_morning_top_snapshot(
    quote: dict[str, Any],
    board: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any] | None:
    price = quote.get("price")
    pre_close = quote.get("preClose")
    open_price = quote.get("open") or price
    if not price or not pre_close:
        return None

    pct = quote.get("pct") or 0
    volume_ratio = quote.get("volumeRatio")
    turnover = quote.get("turnover") or 0
    main_net = quote.get("mainNet") or 0
    super_net = quote.get("superNet") or 0
    amount = quote.get("amount") or 0
    range_position = intraday_position(quote)
    high = quote.get("high") or price
    low = quote.get("low") or price
    avg_price = quote.get("avgPrice") or average_price(amount, quote.get("volume")) or price
    close_to_high = price / high if high else 0
    price_vs_avg = ((price / avg_price) - 1) * 100 if avg_price else 0
    intraday_reversal = ((price / low) - 1) * 100 if low else 0
    open_to_price = ((price / open_price) - 1) * 100 if open_price else 0
    pullback = high_to_close_pullback_pct(quote)
    veto_reasons = morning_top_hard_veto_reasons(quote, now)
    if veto_reasons:
        return None

    criteria = [
        ("Board is hot enough for morning acceleration", (board.get("passed") or 0) >= 4),
        ("Morning acceleration gain zone is matched", AM_TOP_MIN_PCT <= pct <= AM_TOP_MAX_PCT),
        ("Price holds the early high platform", range_position >= 0.78 and close_to_high >= 0.972 and pullback <= 2.8),
        ("Price holds above VWAP", price_vs_avg >= 0.0),
        ("Turnover grows normally for the current minute", morning_min_turnover(now) <= turnover <= 38),
        ("Volume is active without obvious exhaustion", morning_volume_ratio_ok(volume_ratio)),
        ("Main or super capital is net inflow", main_net > 0 or super_net > 0),
        ("Deal amount grows normally for the current minute", amount >= morning_min_amount(now)),
        ("Open has enough upward spread", pct >= 6.5 or open_to_price >= 0.8 or intraday_reversal >= 3.0),
    ]
    passed_labels = [label for label, ok in criteria if ok]
    if len(passed_labels) < 7:
        return None

    buy_plan = choose_morning_top_buy_plan_snapshot(quote, now)
    if not buy_plan:
        return None

    entry = buy_plan["priceRange"][0]
    stop_loss = estimate_morning_top_stop_snapshot(entry, quote)
    target = estimate_morning_top_target_snapshot(entry, price, pre_close, quote, board, buy_plan)
    expected_return = ((target["targetPrice"] / entry) - 1) * 100 if entry else 0
    risk_pct = ((entry / stop_loss) - 1) * 100 if stop_loss else 0
    t1_edge_score = estimate_morning_top_edge_score(
        quote,
        board,
        buy_plan,
        expected_return,
        risk_pct,
        len(passed_labels),
    )
    win_rate = round(
        min(
            95,
            46
            + len(passed_labels) * 4.0
            + (board.get("passed") or 0) * 2.2
            + buy_plan["quality"] * 0.8
            + min(8, t1_edge_score / 13)
            - max(0, risk_pct - 4.0) * 1.8,
        ),
        1,
    )

    return {
        "rank": None,
        "code": quote["code"],
        "name": quote["name"],
        "market": quote.get("market"),
        "price": round2(price),
        "pct": pct,
        "amount": quote.get("amount"),
        "turnover": turnover,
        "industry": quote.get("industry") or board.get("name"),
        "confidence": win_rate,
        "winRate": win_rate,
        "strategyTag": STRATEGY_AM_TOP,
        "t1EdgeScore": t1_edge_score,
        "expectedReturnPct": round2(expected_return),
        "riskPct": round2(risk_pct),
        "board": {
            "code": board["code"],
            "name": board["name"],
            "passed": board.get("passed"),
            "score": board.get("score"),
        },
        "criteria": {
            "board": board.get("criteria", []),
            "stock": [f"[{STRATEGY_AM_TOP}] Early morning front-row setup", *passed_labels],
        },
        "buyPlan": buy_plan,
        "sellPlan": {
            "targetPrice": target["targetPrice"],
            "targetTime": target["targetTime"],
            "strategy": target["strategy"],
            "takeProfit": target["targetPrice"],
            "timeWindow": target["targetTime"],
        },
        "stopPlan": {
            "stopLoss": stop_loss,
            "rules": [
                "Morning top weakens and fails to reseal or hold the high platform",
                "Break the personalized stop or fall back under VWAP with volume",
                "09:26 is a watch/queue signal; 09:31-09:38 is the primary execution window",
                "Do not chase after 09:40 unless it is an unsealed front-row reseal",
            ],
        },
        "sourceLinks": stock_source_links(quote["code"]),
        "sparkline": [],
    }


def choose_buy_plan_snapshot(
    quote: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any] | None:
    price = quote["price"]
    pre_close = quote["preClose"]
    open_price = quote["open"]
    pct = quote.get("pct") or 0
    turnover = quote.get("turnover") or 0
    range_position = intraday_position(quote)
    high = quote.get("high") or price
    low = quote.get("low") or price
    close_to_high = price / high if high else 0
    amount = quote.get("amount") or 0
    avg_price = quote.get("avgPrice") or average_price(amount, quote.get("volume")) or price
    price_vs_avg = ((price / avg_price) - 1) * 100 if avg_price else 0
    open_to_price = ((price / open_price) - 1) * 100 if open_price else 0
    intraday_reversal = ((price / low) - 1) * 100 if low else 0
    pullback = high_to_close_pullback_pct(quote)
    amplitude = quote_amplitude_pct(quote)
    metrics = quote.get("dailyMetrics") or {}
    amount_ratio = metrics.get("amountRatio")
    deviation_ma5 = metrics.get("deviationMA5Pct")
    mid_stage = (
        metrics.get("ma5Rising") is not False
        and trend_persistence_ok(metrics)
        and (deviation_ma5 is None or deviation_ma5 <= 15)
        and (metrics.get("gain5dPct") or 0) < 25
        and (metrics.get("gain10dPct") or 0) < 40
    )

    if (
        is_stable_limit_up_proxy(quote)
        and 3 <= turnover <= 25
        and amount >= TAIL_MIN_AMOUNT
        and mid_stage
    ):
        return make_buy_plan(
            "[TAIL_MAIN] T1 stable limit-up",
            price,
            TAIL_BUY_WINDOW,
            "Only use a stable seal with sector synchronization; repeated opening or fading orders cancel the entry.",
            26,
            9,
            quote,
            STRATEGY_TAIL_MAIN,
            "T1_STABLE_LIMIT_UP",
        )
    if (
        3.0 <= pct <= 7.0
        and (amount_ratio is None or 1.20 <= amount_ratio <= 2.80)
        and 4 <= turnover <= 25
        and range_position >= 0.70
        and pullback <= 2.5
        and close_to_high >= 0.975
        and price_vs_avg >= 0.0
        and metrics.get("closeAboveBreakout") is not False
        and mid_stage
        and amount >= TAIL_MIN_AMOUNT
    ):
        return make_buy_plan(
            "[TAIL_MAIN] T3 mid-trend breakout",
            price,
            TAIL_BUY_WINDOW,
            "Confirm above VWAP and the prior platform from 14:10-14:35; cancel on a late straight-line spike.",
            25,
            8,
            quote,
            STRATEGY_TAIL_MAIN,
            "T3_TREND_BREAKOUT",
        )
    if (
        7.0 <= pct < 9.8
        and amplitude <= 8.0
        and 6 <= turnover <= 25
        and range_position >= 0.80
        and pullback <= 1.5
        and close_to_high >= 0.985
        and price_vs_avg >= 0.8
        and mid_stage
        and amount >= TAIL_MIN_AMOUNT
    ):
        return make_buy_plan(
            "[TAIL_MAIN] T4 strong close below limit",
            price,
            TAIL_BUY_WINDOW,
            "Use only a low-amplitude front-row strong close; high turnover or an unsealed fade is rejected.",
            23,
            7,
            quote,
            STRATEGY_TAIL_MAIN,
            "T4_NEAR_LIMIT_STRONG_CLOSE",
        )
    if (
        2.5 <= pct <= 6.5
        and metrics.get("firstPullbackProxy") is True
        and (amount_ratio is None or amount_ratio <= 1.60)
        and 4 <= turnover <= 20
        and range_position >= 0.65
        and pullback <= 2.5
        and price_vs_avg >= -0.05
        and open_to_price >= 0.5
        and mid_stage
        and amount >= TAIL_MIN_AMOUNT
    ):
        return make_buy_plan(
            "[TAIL_MAIN] T5 first pullback reclaim",
            price,
            TAIL_BUY_WINDOW,
            "Only the first shrinking-volume pullback is valid; repeated VWAP breaks or lost structure cancel it.",
            21,
            6,
            quote,
            STRATEGY_TAIL_MAIN,
            "T5_FIRST_PULLBACK",
        )
    return None


def make_buy_plan(
    label: str,
    anchor_price: float,
    window: str,
    trigger: str,
    quality: int,
    priority: int,
    quote: dict[str, Any] | None = None,
    strategy_tag: str = STRATEGY_TAIL_MAIN,
    signal_type: str | None = None,
) -> dict[str, Any]:
    lower_offset, upper_offset = buy_range_offsets(quote)
    return {
        "type": label,
        "timeWindow": window,
        "trigger": trigger,
        "priceRange": [round2(anchor_price * (1 - lower_offset)), round2(anchor_price * (1 + upper_offset))],
        "quality": quality,
        "priority": priority,
        "strategyTag": strategy_tag,
        "signalType": signal_type,
    }


def choose_morning_top_buy_plan_snapshot(
    quote: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any] | None:
    price = quote["price"]
    pct = quote.get("pct") or 0
    volume_ratio = quote.get("volumeRatio")
    turnover = quote.get("turnover") or 0
    range_position = intraday_position(quote)
    high = quote.get("high") or price
    amount = quote.get("amount") or 0
    avg_price = quote.get("avgPrice") or average_price(amount, quote.get("volume")) or price
    close_to_high = price / high if high else 0
    price_vs_avg = ((price / avg_price) - 1) * 100 if avg_price else 0
    pullback = high_to_close_pullback_pct(quote)
    min_amount = morning_min_amount(now)
    min_turnover = morning_min_turnover(now)

    if (
        9.2 <= pct <= AM_TOP_MAX_PCT
        and min_turnover <= turnover <= 38
        and morning_volume_ratio_ok(volume_ratio, 6.8)
        and range_position >= 0.88
        and close_to_high >= 0.988
        and pullback <= 1.6
        and price_vs_avg >= 0.8
        and amount >= min_amount
    ):
        return make_top_buy_plan(
            "[AM_TOP] near-limit confirmation",
            price,
            AM_TOP_BUY_WINDOW,
            "09:31-09:38 only: confirm the front-row seal/reseal; after 09:40 do not chase a locked board.",
            23,
            8,
        )
    if (
        6.5 <= pct <= 9.6
        and min_turnover <= turnover <= 32
        and morning_volume_ratio_ok(volume_ratio, 6.2)
        and range_position >= 0.78
        and close_to_high >= 0.974
        and pullback <= 2.6
        and price_vs_avg >= 0.15
        and amount >= min_amount
    ):
        return make_top_buy_plan(
            "[AM_TOP] open-strength entry",
            price,
            AM_TOP_BUY_WINDOW,
            "Primary window 09:31-09:38: enter only while the stock remains above VWAP and the early high platform.",
            24,
            9,
        )
    if (
        AM_TOP_MIN_PCT <= pct <= 7.8
        and min_turnover <= turnover <= 28
        and morning_volume_ratio_ok(volume_ratio, 5.8)
        and range_position >= 0.76
        and close_to_high >= 0.972
        and pullback <= 2.8
        and price_vs_avg >= 0.0
        and amount >= min_amount
    ):
        return make_top_buy_plan(
            "[AM_TOP] early lift-off entry",
            price,
            AM_TOP_BUY_WINDOW,
            "Catch the 09:31-09:38 lift-off before the limit-up rush; cancel immediately if it loses VWAP.",
            22,
            7,
        )
    return None


def make_top_buy_plan(
    label: str,
    anchor_price: float,
    window: str,
    trigger: str,
    quality: int,
    priority: int,
) -> dict[str, Any]:
    return {
        "type": label,
        "timeWindow": window,
        "trigger": trigger,
        "priceRange": [round2(anchor_price * 0.996), round2(anchor_price * 1.002)],
        "quality": quality,
        "priority": priority,
        "strategyTag": STRATEGY_AM_TOP,
    }


def next_day_plan(initial_plan: str) -> dict[str, Any]:
    if initial_plan == "PLAN_T":
        first_sell_ratio = [0.20, 0.30]
        neutral_remainder = 0.30
        strong_remainder = [0.50, 0.70]
    else:
        first_sell_ratio = [0.40, 0.50]
        neutral_remainder = 0.20
        strong_remainder = [0.50, 0.60]
    return {
        "auctionWatchTime": "09:25-09:30",
        "firstNodeTime": "09:30-09:35",
        "firstSellRatio": first_sell_ratio,
        "openingOverride": True,
        "strongRepairAction": "DEFER_FIRST_SELL_TO_0935",
        "classifyTime": "09:35",
        "weakAction": "SELL_ALL_REMAINDER_NOW",
        "neutralTotalRemainder": neutral_remainder,
        "strongRemainder": strong_remainder,
        "finalExitTime": "10:00",
        "limitUpException": True,
    }


def estimate_target_snapshot(
    entry: float,
    price: float,
    pre_close: float,
    quote: dict[str, Any],
    board: dict[str, Any],
    buy_plan: dict[str, Any],
    final_score: float = 74,
    initial_plan: str = "PLAN_S",
) -> dict[str, Any]:
    base_gain = 0.012
    turnover = quote.get("turnover") or 0
    amount = quote.get("amount") or 0
    main_net = max(0, quote.get("mainNet") or 0) + max(0, quote.get("superNet") or 0)
    net_ratio = main_net / amount if amount else 0
    range_position = intraday_position(quote)
    high = quote.get("high") or price
    avg_price = quote.get("avgPrice") or average_price(amount, quote.get("volume")) or price
    close_to_high = price / high if high else 0
    price_vs_avg = ((price / avg_price) - 1) * 100 if avg_price else 0
    metrics = quote.get("dailyMetrics") or {}
    amount_ratio = metrics.get("amountRatio")

    if (board.get("passed") or 0) >= 5:
        base_gain += 0.006
    if (board.get("limitUpCount") or 0) >= 2:
        base_gain += 0.006
    elif (board.get("limitUpCount") or 0) >= 1:
        base_gain += 0.003
    if amount_ratio is not None and 1.3 <= amount_ratio <= 2.2:
        base_gain += 0.006
    if 6 <= turnover <= 16:
        base_gain += 0.005
    if main_net > 0:
        base_gain += clamp(net_ratio * 0.4, 0, 0.008)
    if range_position >= 0.84 and close_to_high >= 0.985:
        base_gain += 0.006
    elif range_position >= 0.78:
        base_gain += 0.003
    if price_vs_avg >= 1.2:
        base_gain += 0.004
    if final_score >= 84:
        base_gain += 0.008
    if initial_plan == "PLAN_T":
        base_gain += 0.006
    if is_stable_limit_up_proxy(quote):
        base_gain += 0.018

    target_gain = clamp(base_gain, 0.008, 0.080)
    target_price = round2(min(entry * (1 + target_gain), entry * 1.098))
    return {
        "targetPrice": target_price,
        "targetTime": TAIL_TARGET_TIME,
        "strategy": "v3.1: freeze the overnight target, confirm opening repair at 09:30-09:35, and exit non-limit-up remainder at 10:00.",
    }


def estimate_morning_top_target_snapshot(
    entry: float,
    price: float,
    pre_close: float,
    quote: dict[str, Any],
    board: dict[str, Any],
    buy_plan: dict[str, Any],
) -> dict[str, Any]:
    base_gain = 0.034
    pct = quote.get("pct") or 0
    turnover = quote.get("turnover") or 0
    volume_ratio = quote.get("volumeRatio") or 0
    amount = quote.get("amount") or 0
    main_net = max(0, quote.get("mainNet") or 0) + max(0, quote.get("superNet") or 0)
    net_ratio = main_net / amount if amount else 0
    range_position = intraday_position(quote)
    high = quote.get("high") or price
    avg_price = quote.get("avgPrice") or average_price(amount, quote.get("volume")) or price
    close_to_high = price / high if high else 0
    price_vs_avg = ((price / avg_price) - 1) * 100 if avg_price else 0

    if (board.get("passed") or 0) >= 5:
        base_gain += 0.01
    if (board.get("limitUpCount") or 0) >= 1:
        base_gain += 0.008
    if 7.0 <= pct <= 9.4:
        base_gain += 0.014
    elif 9.4 < pct <= 10.3:
        base_gain += 0.012
    if 6 <= turnover <= 24:
        base_gain += 0.01
    elif 24 < turnover <= 38:
        base_gain += 0.004
    if 0.8 <= volume_ratio <= 4.5:
        base_gain += 0.008
    if range_position >= 0.9 and close_to_high >= 0.99:
        base_gain += 0.01
    if price_vs_avg >= 3.0:
        base_gain += 0.008
    if main_net > 0:
        base_gain += clamp(net_ratio * 0.5, 0, 0.012)
    if buy_plan["priority"] >= 7:
        base_gain += 0.008

    target_gain = clamp(base_gain, 0.030, 0.090)
    target_price = round2(min(max(entry * (1 + target_gain), price * 1.010), entry * 1.098))
    return {
        "targetPrice": target_price,
        "targetTime": "Next trading day 09:30-10:00; sell before 10:00 unless the board remains sealed.",
        "strategy": "AM_TOP setup: catch the next-morning premium after 09:31-09:38 front-row acceleration; after 09:40 only monitor seal strength or reseal.",
    }


def pre_rank_candidate(
    quote: dict[str, Any],
    board: dict[str, Any],
    active_strategies: set[str] | None = None,
) -> float:
    if active_strategies is None:
        active_strategies = {STRATEGY_TAIL_MAIN, STRATEGY_AM_TOP}
    pct = quote.get("pct") or 0
    turnover = quote.get("turnover") or 0
    volume_ratio = quote.get("volumeRatio") or 0
    amount = quote.get("amount") or 0
    main_net = max(0, quote.get("mainNet") or 0) + max(0, quote.get("superNet") or 0)
    net_ratio = main_net / amount if amount else 0
    range_position = intraday_position(quote)
    high = quote.get("high") or quote.get("price") or 0
    price = quote.get("price") or 0
    avg_price = quote.get("avgPrice") or average_price(amount, quote.get("volume")) or price
    close_to_high = price / high if high else 0
    price_vs_avg = ((price / avg_price) - 1) * 100 if avg_price else 0
    pullback = high_to_close_pullback_pct(quote)
    sweet_gain = 1 - min(abs(pct - 5.4) / 2.2, 1)
    sweet_turnover = 1 - min(abs(turnover - 16.0) / 14.0, 1)
    sweet_volume = 1 - min(abs(volume_ratio - 2.6) / 3.2, 1)
    tail_score = (
        (board.get("score") or 0) * 0.35
        + sweet_gain * 24
        + sweet_turnover * 16
        + sweet_volume * 10
        + range_position * 15
        + clamp((close_to_high - 0.97) * 260, 0, 8)
        + clamp(price_vs_avg * 2.0, 0, 12)
        + clamp(net_ratio * 280, 0, 10)
        + min(amount / 800_000_000, 10)
        - max(0, pct - 7.6) * 7
        - max(0, turnover - 32) * 1.2
        - max(0, volume_ratio - 5.8) * 3
        - max(0, pullback - TAIL_PREFERRED_MAX_PULLBACK) * 5
    )
    early_top_gain = 1 - min(abs(pct - 7.8) / 2.2, 1)
    near_limit_gain = 1 - min(abs(pct - 9.7) / 1.4, 1)
    top_gain = max(early_top_gain, near_limit_gain * 0.92)
    top_turnover = 1 - min(abs(turnover - 14.0) / 18.0, 1)
    top_score = (
        (board.get("score") or 0) * 0.32
        + top_gain * 26
        + top_turnover * 12
        + clamp(volume_ratio * 2.0, 0, 9)
        + range_position * 16
        + clamp((close_to_high - 0.98) * 360, 0, 10)
        + clamp(price_vs_avg * 1.8, 0, 12)
        + clamp(net_ratio * 240, 0, 8)
        + min(amount / 1_000_000_000, 10)
        - max(0, pct - 10.0) * 5
        - max(0, high_to_close_pullback_pct(quote) - 2.2) * 5
    )
    scores = []
    if STRATEGY_TAIL_MAIN in active_strategies:
        scores.append(tail_score)
    if STRATEGY_AM_TOP in active_strategies:
        scores.append(top_score)
    return round2(max(scores) if scores else 0)


def estimate_stop_snapshot(entry: float, quote: dict[str, Any]) -> float:
    price = quote.get("price") or entry
    pre_close = quote.get("preClose") or price
    open_price = quote.get("open") or price
    low = quote.get("low") or price
    high = quote.get("high") or price
    amount = quote.get("amount") or 0
    avg_price = quote.get("avgPrice") or average_price(amount, quote.get("volume")) or price
    turnover = quote.get("turnover") or 0
    amplitude = quote.get("amplitude")
    if amplitude is None and high and low and pre_close:
        amplitude = ((high - low) / pre_close) * 100
    amplitude = amplitude or 5
    range_position = intraday_position(quote)

    volatility_room = clamp(amplitude * 0.0040, 0.024, 0.044)
    if range_position >= 0.82:
        volatility_room += 0.003
    if turnover > 22:
        volatility_room += 0.004
    volatility_room = min(volatility_room, 0.048)

    volatility_stop = entry * (1 - volatility_room)
    structure_stop = max(low * 1.006, avg_price * 0.992, open_price * 0.990, pre_close * 1.003)
    ceiling = entry * 0.982
    floor = entry * 0.958
    stop_loss = max(floor, volatility_stop, min(ceiling, structure_stop))
    return round2(min(ceiling, stop_loss))


def estimate_morning_top_stop_snapshot(entry: float, quote: dict[str, Any]) -> float:
    price = quote.get("price") or entry
    pre_close = quote.get("preClose") or price
    open_price = quote.get("open") or price
    amount = quote.get("amount") or 0
    avg_price = quote.get("avgPrice") or average_price(amount, quote.get("volume")) or price
    high_platform_stop = max(avg_price * 0.988, open_price * 0.995, pre_close * 1.035)
    ceiling = entry * 0.982
    floor = entry * 0.952
    stop_loss = max(floor, min(ceiling, high_platform_stop))
    return round2(stop_loss)


def estimate_morning_top_edge_score(
    quote: dict[str, Any],
    board: dict[str, Any],
    buy_plan: dict[str, Any],
    expected_return: float,
    risk_pct: float,
    passed_count: int,
) -> float:
    amount = quote.get("amount") or 0
    main_net = max(0, quote.get("mainNet") or 0) + max(0, quote.get("superNet") or 0)
    net_ratio = main_net / amount if amount else 0
    reward_risk = expected_return / max(risk_pct, 0.8)
    pct = quote.get("pct") or 0
    turnover = quote.get("turnover") or 0
    price = quote.get("price") or 0
    high = quote.get("high") or price
    avg_price = quote.get("avgPrice") or average_price(amount, quote.get("volume")) or price
    close_to_high = price / high if high else 0
    price_vs_avg = ((price / avg_price) - 1) * 100 if avg_price else 0
    pct_bonus = max(0, 1 - abs(pct - 9.9) / 1.4) * 12
    turnover_bonus = max(0, 1 - abs(turnover - 18.0) / 20.0) * 8
    return round2(
        expected_return * 7.0
        + reward_risk * 8.5
        + (board.get("score") or 0) * 0.15
        + buy_plan["quality"] * 1.1
        + passed_count * 2.0
        + intraday_position(quote) * 9
        + clamp((close_to_high - 0.985) * 380, 0, 10)
        + clamp(price_vs_avg * 2.0, 0, 12)
        + clamp(net_ratio * 220, 0, 8)
        + pct_bonus
        + turnover_bonus
        - max(0, risk_pct - 4.2) * 4
    )


def estimate_t1_edge_score(
    quote: dict[str, Any],
    board: dict[str, Any],
    buy_plan: dict[str, Any],
    expected_return: float,
    risk_pct: float,
    passed_count: int,
) -> float:
    amount = quote.get("amount") or 0
    main_net = max(0, quote.get("mainNet") or 0) + max(0, quote.get("superNet") or 0)
    net_ratio = main_net / amount if amount else 0
    reward_risk = expected_return / max(risk_pct, 0.8)
    pct = quote.get("pct") or 0
    turnover = quote.get("turnover") or 0
    price = quote.get("price") or 0
    high = quote.get("high") or price
    avg_price = quote.get("avgPrice") or average_price(amount, quote.get("volume")) or price
    close_to_high = price / high if high else 0
    price_vs_avg = ((price / avg_price) - 1) * 100 if avg_price else 0
    pct_bonus = max(0, 1 - abs(pct - 5.7) / 2.4) * 10
    turnover_bonus = max(0, 1 - abs(turnover - 22.0) / 16.0) * 8
    return round2(
        expected_return * 7.4
        + reward_risk * 9.0
        + (board.get("score") or 0) * 0.16
        + buy_plan["quality"] * 1.1
        + passed_count * 2.2
        + intraday_position(quote) * 9
        + clamp((close_to_high - 0.975) * 300, 0, 9)
        + clamp(price_vs_avg * 2.2, 0, 12)
        + clamp(net_ratio * 220, 0, 8)
        + pct_bonus
        + turnover_bonus
        - max(0, risk_pct - 3.8) * 4
    )


def buy_range_offsets(quote: dict[str, Any] | None) -> tuple[float, float]:
    if not quote:
        return 0.008, 0.004
    amplitude = quote.get("amplitude") or 5
    pct = quote.get("pct") or 0
    turnover = quote.get("turnover") or 0
    lower_offset = clamp(amplitude * 0.0016 + (0.003 if pct > 6.5 else 0), 0.006, 0.018)
    upper_offset = clamp(0.0025 + (0.001 if turnover < 8 else 0), 0.002, 0.006)
    return lower_offset, upper_offset


def intraday_position(quote: dict[str, Any]) -> float:
    price = quote.get("price")
    high = quote.get("high")
    low = quote.get("low")
    if not price or not high or not low or high <= low:
        return 0.5
    return clamp((price - low) / (high - low), 0, 1)


def stock_universe_allowed(code: str) -> bool:
    if not re.match(r"^(00|30|60|68|83|87|43)\d{4}$", code):
        return False
    if not ALLOW_GROWTH_BOARDS and code.startswith(GROWTH_BOARD_PREFIXES):
        return False
    return True


def active_strategy_windows(now: datetime) -> set[str]:
    minute_of_day = now.hour * 60 + now.minute
    active: set[str] = set()
    if 9 * 60 + 25 <= minute_of_day <= 9 * 60 + 45:
        active.add(STRATEGY_AM_TOP)
    if 13 * 60 + 25 <= minute_of_day <= 14 * 60 + 50:
        active.add(STRATEGY_TAIL_MAIN)
    return active


def is_morning_top_setup(
    quote: dict[str, Any],
    board: dict[str, Any],
    now: datetime | None = None,
) -> bool:
    if (board.get("passed") or 0) < 4:
        return False
    if not morning_top_prefilter(quote, now):
        return False
    if morning_top_hard_veto_reasons(quote, now):
        return False
    price = quote.get("price")
    high = quote.get("high") or price
    amount = quote.get("amount") or 0
    avg_price = quote.get("avgPrice") or average_price(amount, quote.get("volume")) or price
    if not price or not high or not avg_price:
        return False
    close_to_high = price / high if high else 0
    price_vs_avg = ((price / avg_price) - 1) * 100 if avg_price else 0
    return intraday_position(quote) >= 0.74 and close_to_high >= 0.970 and price_vs_avg >= 0.0


def fetch_board_members(board_code: str) -> list[dict[str, Any]]:
    fields = "f12,f13,f14,f2,f3,f4,f5,f6,f7,f8,f10,f15,f16,f17,f18,f20,f21,f62,f66,f100"
    rows = safe_clist("Eastmoney", f"b:{board_code}+f:!50", fields, page_size=MAX_MEMBERS_PER_BOARD)
    members = [normalize_stock_quote(row) for row in rows]
    members = [item for item in members if item.get("code") and item.get("price")]
    members.sort(key=lambda item: (item.get("pct") or -999, item.get("amount") or 0), reverse=True)
    return members


def normalize_stock_quote(row: dict[str, Any]) -> dict[str, Any]:
    code = str(row.get("f12") or "")
    volume = number(row.get("f5"))
    amount = number(row.get("f6"))
    return {
        "code": code,
        "name": text(row.get("f14")),
        "market": stock_market(code),
        "price": number(row.get("f2")),
        "pct": number(row.get("f3")),
        "change": number(row.get("f4")),
        "volume": volume,
        "amount": amount,
        "avgPrice": average_price(amount, volume),
        "amplitude": number(row.get("f7")),
        "turnover": number(row.get("f8")),
        "volumeRatio": number(row.get("f10")),
        "high": number(row.get("f15")),
        "low": number(row.get("f16")),
        "open": number(row.get("f17")),
        "preClose": number(row.get("f18")),
        "floatMarketCap": number(row.get("f21")),
        "mainNet": number(row.get("f62")),
        "superNet": number(row.get("f66")),
        "industry": text(row.get("f100")),
    }


def stock_prefilter(
    item: dict[str, Any],
    active_strategies: set[str] | None = None,
    now: datetime | None = None,
) -> bool:
    if active_strategies is None:
        active_strategies = {STRATEGY_TAIL_MAIN, STRATEGY_AM_TOP}
    return (
        (STRATEGY_TAIL_MAIN in active_strategies and tail_prefilter(item))
        or (STRATEGY_AM_TOP in active_strategies and morning_top_prefilter(item, now))
    )


def tail_prefilter(item: dict[str, Any]) -> bool:
    code = item.get("code") or ""
    name = item.get("name") or ""
    if not stock_universe_allowed(code):
        return False
    if any(flag in name.upper() for flag in ("ST", "*ST", "退")):
        return False
    turnover = item.get("turnover")
    pct = item.get("pct") or 0
    amount = item.get("amount") or 0
    volume_ratio = item.get("volumeRatio")
    if turnover is None or turnover < 3.0 or turnover > TAIL_HARD_MAX_TURNOVER:
        return False
    price = item.get("price") or 0
    avg_price = item.get("avgPrice") or average_price(amount, item.get("volume")) or price
    price_vs_avg = ((price / avg_price) - 1) * 100 if price and avg_price else -99
    return (
        2.5 <= pct <= TAIL_MAX_PCT
        and amount >= TAIL_MIN_AMOUNT
        and (volume_ratio is None or volume_ratio <= 7.0)
        and intraday_position(item) >= 0.55
        and high_to_close_pullback_pct(item) <= TAIL_HARD_MAX_PULLBACK + 0.4
        and price_vs_avg >= -0.3
    )


def morning_top_prefilter(
    item: dict[str, Any],
    now: datetime | None = None,
) -> bool:
    code = item.get("code") or ""
    name = item.get("name") or ""
    if not stock_universe_allowed(code):
        return False
    if any(flag in name.upper() for flag in ("ST", "*ST", "閫€")):
        return False
    turnover = item.get("turnover")
    pct = item.get("pct") or 0
    amount = item.get("amount") or 0
    volume_ratio = item.get("volumeRatio")
    if turnover is None or turnover < morning_min_turnover(now) or turnover > TAIL_HARD_MAX_TURNOVER:
        return False
    return (
        AM_TOP_MIN_PCT <= pct <= AM_TOP_MAX_PCT
        and amount >= morning_min_amount(now)
        and morning_volume_ratio_ok(volume_ratio)
        and intraday_position(item) >= 0.72
        and high_to_close_pullback_pct(item) <= 3.0
    )


def fetch_news() -> list[dict[str, Any]]:
    news = []
    for source, url in [
        ("Eastmoney News", "https://finance.eastmoney.com/a/cjjsp.html"),
        ("10jqka", "https://stock.10jqka.com.cn/"),
        ("Yicai", "https://www.yicai.com/news/"),
    ]:
        if deadline_hit():
            break
        html = fetch_text(source, url)
        if not html:
            continue
        for href, label in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.I):
            title = clean_html(label)
            if useful_news_title(title):
                news.append({"source": source, "title": title, "url": parse.urljoin(url, href), "time": ""})
            if len(news) >= 8:
                return dedupe_news(news)
    return dedupe_news(news)


def safe_clist(
    source: str,
    fs: str,
    fields: str,
    page_size: int,
    descending: bool = True,
) -> list[dict[str, Any]]:
    params = {
        "pn": "1",
        "pz": str(page_size),
        "po": "1" if descending else "0",
        "np": "1",
        "ut": EASTMONEY_UT,
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": fs,
        "fields": fields,
    }
    try:
        data = eastmoney_json(source, "https://push2.eastmoney.com/api/qt/clist/get", params)
        return data.get("data", {}).get("diff", []) if data else []
    except Exception as exc:
        message = f"{source} clist failed: {short_error(exc)}"
        print(message)
        errors.append(message)
        return []


def eastmoney_json(source: str, url: str, params: dict[str, Any]) -> dict[str, Any]:
    query = parse.urlencode(params)
    urls = [f"{url}?{query}"]
    if "push2.eastmoney.com" in url:
        urls = [f"{url.replace('push2.eastmoney.com', host)}?{query}" for host in EASTMONEY_HOSTS]

    last_exc: Exception | None = None
    for full_url in urls:
        if deadline_hit():
            break
        try:
            payload = fetch_bytes(source, full_url, referer="https://quote.eastmoney.com/").decode("utf-8", "ignore")
            parsed = json.loads(strip_jsonp(payload))
            rows = parsed.get("data", {}).get("diff")
            if rows:
                mark_source(source, True, full_url, "OK")
            return parsed
        except Exception as exc:
            last_exc = exc
    raise RuntimeError(last_exc or "request timeout")


def fetch_text(source: str, url: str) -> str:
    try:
        raw = fetch_bytes(source, url, accept="text/html,application/xhtml+xml")
        mark_source(source, True, url, "Optional news source OK")
        return raw.decode("utf-8", "ignore")
    except Exception as exc:
        errors.append(f"{source} news skipped: {short_error(exc)}")
        mark_source(source, True, url, "Optional news source skipped; quote data is unaffected.")
        return ""


def fetch_bytes(
    source: str,
    url: str,
    referer: str = "",
    accept: str = "application/json,text/plain,*/*",
) -> bytes:
    req = request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": accept,
            "Referer": referer or url,
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    try:
        with request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return response.read()
    except error.HTTPError as exc:
        if exc.code in (403, 404, 429, 500, 502, 503, 504):
            raise RuntimeError(f"HTTP {exc.code}") from exc
        raise
    except (error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(short_error(exc)) from exc


def strip_jsonp(payload: str) -> str:
    payload = payload.strip()
    if payload.startswith("{"):
        return payload
    match = re.search(r"\((\{.*\})\)\s*;?$", payload, re.S)
    return match.group(1) if match else payload


def dedupe_boards(boards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped = {}
    for board in boards:
        if board.get("code"):
            deduped[board["code"]] = board
    result = list(deduped.values())
    result.sort(key=lambda item: (item.get("pct") or -999, item.get("amount") or 0), reverse=True)
    return result


def weighted_average(items: list[dict[str, Any]], value_key: str, weight_key: str) -> float | None:
    weighted_sum = 0.0
    total_weight = 0.0
    simple_values = []
    for item in items:
        value = item.get(value_key)
        if value is None:
            continue
        simple_values.append(value)
        weight = item.get(weight_key) or 0
        if weight > 0:
            weighted_sum += value * weight
            total_weight += weight
    if total_weight:
        return round2(weighted_sum / total_weight)
    if simple_values:
        return round2(sum(simple_values) / len(simple_values))
    return None


def average_price(amount: float | None, volume: float | None) -> float | None:
    if not amount or not volume:
        return None
    return round2(amount / (volume * 100))


def strip_members(boards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: value for key, value in board.items() if key != "members"} for board in boards]


def board_continuous_ok(
    code: str,
    current_ranks: dict[str, int],
    history: dict[str, Any],
    current_date: str | None = None,
) -> bool:
    current = current_ranks.get(code, 999)
    history_items = [
        item
        for item in history.get("items", [])
        if not current_date or item.get("date") != current_date
    ]
    previous = [item.get("ranks", {}).get(code, 999) for item in history_items[-2:]]
    two_day_top10 = bool(previous and current <= 10 and previous[-1] <= 10)
    three_day_top20 = bool(
        len(previous) >= 2
        and current <= 20
        and previous[-1] <= 20
        and previous[-2] <= 20
    )
    return two_day_top10 or three_day_top20


def board_amount_ratio(board: dict[str, Any], history: dict[str, Any], now: datetime) -> float | None:
    code = board.get("code")
    previous_amounts = [
        item.get("amounts", {}).get(code)
        for item in history.get("items", [])[-5:]
        if item.get("date") != now.strftime("%Y-%m-%d") and item.get("amounts", {}).get(code)
    ]
    if not previous_amounts:
        return None
    current_amount = project_amount_to_close(board.get("amount") or 0, now)
    baseline = sum(previous_amounts) / len(previous_amounts)
    return current_amount / baseline if baseline else None


def update_board_history(history: dict[str, Any], today: str, boards: list[dict[str, Any]]) -> None:
    ranks = {board["code"]: board["rank"] for board in boards if board.get("rank")}
    amounts = {board["code"]: board.get("amount") for board in boards if board.get("amount")}
    items = [entry for entry in history.get("items", []) if entry.get("date") != today]
    items.append({"date": today, "ranks": ranks, "amounts": amounts})
    write_json(BOARD_HISTORY_PATH, {"items": items[-30:]})


def is_late_chase(item: dict[str, Any]) -> bool:
    pct = item.get("pct")
    code = item.get("code") or ""
    name = item.get("name") or ""
    if pct is None:
        return False
    if "ST" in name.upper():
        return pct >= 4.2
    if code.startswith(("30", "68")):
        return pct >= 16.5
    return pct >= 8.4


def is_limit_up(item: dict[str, Any]) -> bool:
    pct = item.get("pct")
    code = item.get("code") or ""
    name = item.get("name") or ""
    if pct is None:
        return False
    if "ST" in name.upper():
        return pct >= 4.8
    if code.startswith(("30", "68")):
        return pct >= 19.5
    return pct >= 9.8


def is_limit_down(item: dict[str, Any]) -> bool:
    pct = item.get("pct")
    code = item.get("code") or ""
    name = item.get("name") or ""
    if pct is None:
        return False
    if "ST" in name.upper():
        return pct <= -4.8
    if code.startswith(("30", "68")):
        return pct <= -19.5
    return pct <= -9.8


def touched_limit_up(item: dict[str, Any]) -> bool:
    high = item.get("high")
    pre_close = item.get("preClose")
    code = item.get("code") or ""
    name = item.get("name") or ""
    if not high or not pre_close:
        return is_limit_up(item)
    limit_rate = 0.05 if "ST" in name.upper() else 0.20 if code.startswith(("30", "68")) else 0.10
    return high >= pre_close * (1 + limit_rate * 0.985)


def dedupe_news(news: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for item in news:
        if item["title"] in seen:
            continue
        seen.add(item["title"])
        result.append(item)
    return result[:8]


def useful_news_title(title: str) -> bool:
    if len(title) < 8 or len(title) > 80:
        return False
    keywords = ("A股", "股市", "市场", "板块", "资金", "沪指", "深成指", "创业板", "证券", "行情")
    return any(keyword in title for keyword in keywords)


def clean_html(raw: str) -> str:
    raw = re.sub(r"<script.*?</script>", "", raw, flags=re.S | re.I)
    raw = re.sub(r"<style.*?</style>", "", raw, flags=re.S | re.I)
    raw = re.sub(r"<[^>]+>", "", raw)
    return raw.replace("&nbsp;", " ").strip()


def stock_market(code: str) -> str:
    if code.startswith("6"):
        return "SH"
    if code.startswith(("4", "8")):
        return "BJ"
    return "SZ"


def stock_source_links(code: str) -> list[dict[str, str]]:
    prefix = "sh" if code.startswith("6") else "sz"
    return [
        {"name": "Eastmoney quote", "url": f"https://quote.eastmoney.com/{prefix}{code}.html"},
        {"name": "10jqka stock page", "url": f"https://stockpage.10jqka.com.cn/{code}/"},
        {"name": "Yicai news", "url": "https://www.yicai.com/news/"},
    ]


def deadline_hit() -> bool:
    return time.monotonic() - STARTED >= MAX_RUNTIME_SECONDS


def remaining_seconds() -> float:
    return MAX_RUNTIME_SECONDS - (time.monotonic() - STARTED)


def clamp(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)


def round2(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value) + 1e-9, 2)


def number(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def text(value: Any) -> str:
    return str(value or "").strip()


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def mark_source(name: str, ok: bool, url: str, note: str) -> None:
    previous = source_health.get(name)
    source_health[name] = {
        "name": name,
        "ok": bool(ok or (previous and previous.get("ok"))),
        "url": url,
        "note": note,
    }


def source_list(previous: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    previous_sources = {}
    if previous:
        for item in previous.get("meta", {}).get("sourceHealth", []):
            if item.get("name"):
                previous_sources[item["name"]] = item

    defaults = [
        ("Eastmoney", "https://quote.eastmoney.com/", "Quote, board, and stock snapshot source", False),
        ("10jqka", "https://www.10jqka.com.cn/", "Optional news/reference source", True),
        ("Yicai", "https://www.yicai.com/", "Optional news/reference source", True),
    ]
    for name, url, note, optional_ok in defaults:
        if name in source_health:
            continue
        previous_item = previous_sources.get(name)
        if previous_item and previous_item.get("ok"):
            source_health[name] = {**previous_item, "note": "Previous successful source status retained during fallback."}
        else:
            source_health[name] = {"name": name, "ok": optional_ok, "url": url, "note": note}
    return list(source_health.values())


def short_error(exc: Any) -> str:
    message = str(exc)
    message = re.sub(r"\s+", " ", message).strip()
    message = message.encode("ascii", "ignore").decode("ascii") or exc.__class__.__name__
    return message[:180]


if __name__ == "__main__":
    main()
