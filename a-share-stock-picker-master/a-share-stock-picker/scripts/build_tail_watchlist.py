#!/usr/bin/env python3
import json
import sys
from pathlib import Path


def load_market_metrics(path):
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {item["ticker"]: item.get("metrics", {}) for item in data.get("universe", []) if item.get("ticker")}


def to_float(value):
    try:
        return float(value)
    except Exception:
        return None


def pct(base, current):
    if base in (None, 0) or current is None:
        return None
    return (current - base) / base * 100.0


def capital_flow_ratio(metrics):
    net_inflow = to_float(metrics.get("netInflow"))
    amount = to_float(metrics.get("amount"))
    if net_inflow is None or amount in (None, 0):
        return None
    return net_inflow / amount


def capital_flow_label(metrics):
    net_inflow = to_float(metrics.get("netInflow"))
    ratio = capital_flow_ratio(metrics)
    if net_inflow is None:
        return "待确认"
    if net_inflow >= 500_000_000 or (ratio is not None and ratio >= 0.08):
        return "主力净流入较强"
    if net_inflow >= 100_000_000 or (ratio is not None and ratio >= 0.03):
        return "主力净流入为正"
    if net_inflow <= -500_000_000 or (ratio is not None and ratio <= -0.08):
        return "主力净流出较强"
    if net_inflow < 0:
        return "主力净流出"
    return "主力资金中性"


def sma(values, n):
    if len(values) < n or n <= 0:
        return None
    values = values[-n:]
    return sum(values) / len(values)


def atr(rows, n=14):
    if len(rows) < 2:
        return None
    trs = []
    prev_close = to_float(rows[0].get("close"))
    for row in rows[1:]:
        high = to_float(row.get("high"))
        low = to_float(row.get("low"))
        close = to_float(row.get("close"))
        if None in (high, low, close, prev_close):
            prev_close = close
            continue
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        prev_close = close
    if not trs:
        return None
    if len(trs) < n:
        return sum(trs) / len(trs)
    return sum(trs[-n:]) / n


def summarize_rows(rows):
    closes = [to_float(row.get("close")) for row in rows if to_float(row.get("close")) is not None]
    highs = [to_float(row.get("high")) for row in rows if to_float(row.get("high")) is not None]
    lows = [to_float(row.get("low")) for row in rows if to_float(row.get("low")) is not None]
    amounts = [to_float(row.get("amount")) for row in rows if to_float(row.get("amount")) is not None]
    if not closes:
        return {}
    return {
        "prev_open": to_float(rows[-1].get("open")),
        "prev_close": closes[-1],
        "high_5": max(highs[-5:]) if highs else None,
        "low_5": min(lows[-5:]) if lows else None,
        "high_20": max(highs[-20:]) if highs else None,
        "low_20": min(lows[-20:]) if lows else None,
        "high_60": max(highs[-60:]) if highs else None,
        "low_60": min(lows[-60:]) if lows else None,
        "ma5": sma(closes, 5),
        "ma20": sma(closes, 20),
        "ma60": sma(closes, 60),
        "atr14": atr(rows, 14),
        "avg_amount_5": sum(amounts[-5:]) / len(amounts[-5:]) if len(amounts) >= 5 else (sum(amounts) / len(amounts) if amounts else None),
        "rows": len(rows),
    }


def score_candidate(summary, snapshot, market_metrics=None):
    score = 35
    notes = []

    if summary.get("rows", 0) >= 20 and snapshot.get("status") == "verified":
        score += 15
        notes.append("历史窗口和分时数据完整")

    avg_amount_5 = summary.get("avg_amount_5")
    if avg_amount_5 is not None:
        if avg_amount_5 >= 1_500_000_000:
            score += 15
            notes.append("近5日成交额高，流动性优秀")
        elif avg_amount_5 >= 500_000_000:
            score += 10
            notes.append("近5日成交额较好，流动性合格")
        elif avg_amount_5 >= 200_000_000:
            score += 4

    change_day = snapshot.get("changeFromPrevClosePct")
    if change_day is not None:
        if 1.0 <= change_day <= 5.0:
            score += 12
            notes.append("当日涨幅适中，次日仍有可交易性")
        elif 0.0 < change_day < 1.0:
            score += 6
        elif 5.0 < change_day <= 7.0:
            score += 4
        elif change_day > 7.0:
            score -= 6
            notes.append("当日涨幅过大，次日容易高开兑现")
        else:
            score -= 10
            notes.append("当日未体现强势")

    change_1400 = snapshot.get("changeFrom1400Pct")
    if change_1400 is not None:
        if change_1400 >= 0.8:
            score += 10
            notes.append("14:00 后尾盘资金继续回流")
        elif change_1400 >= 0.3:
            score += 6
        elif change_1400 <= -0.5:
            score -= 8
            notes.append("14:00 后尾盘转弱")

    range_position = snapshot.get("rangePosition")
    if range_position is not None:
        if range_position >= 0.8:
            score += 10
            notes.append("尾盘收在日内高位附近")
        elif range_position >= 0.65:
            score += 4
        elif range_position <= 0.35:
            score -= 8
            notes.append("尾盘收在日内低位，次日承接风险偏高")

    late_volume_share = snapshot.get("lateVolumeShare")
    if late_volume_share is not None:
        if late_volume_share >= 0.22:
            score += 6
        elif late_volume_share <= 0.12:
            score -= 3

    intraday_close = snapshot.get("intradayClose")
    high_5 = summary.get("high_5")
    low_20 = summary.get("low_20")
    high_20 = summary.get("high_20")
    if None not in (intraday_close, low_20, high_20) and high_20 != low_20:
        pos20 = (intraday_close - low_20) / (high_20 - low_20)
        if 0.55 <= pos20 <= 0.85:
            score += 8
            notes.append("处于20日结构的中上沿，位置仍可接受")
        elif pos20 > 0.9:
            score -= 4
        elif pos20 < 0.35:
            score -= 6

    if None not in (intraday_close, high_5) and high_5 > 0:
        extension = intraday_close / high_5
        if extension > 1.04:
            score -= 8
            notes.append("偏离近5日高点过多，尾盘追价性价比下降")

    metrics = market_metrics or {}
    net_inflow = to_float(metrics.get("netInflow"))
    amount = to_float(metrics.get("amount"))
    turnover = to_float(metrics.get("turnoverPct"))
    flow_ratio = capital_flow_ratio(metrics)
    if amount is not None:
        if amount >= 3_000_000_000:
            score += 6
            notes.append("全市场资金成交额靠前")
        elif amount >= 1_000_000_000:
            score += 3
    if turnover is not None:
        if 3 <= turnover <= 20:
            score += 4
        elif turnover > 25:
            score -= 2
    if net_inflow is not None:
        if net_inflow >= 500_000_000:
            score += 14
            notes.append("主力资金净流入较强，隔夜承接更有基础")
        elif net_inflow >= 100_000_000:
            score += 8
            notes.append("主力资金净流入为正")
        elif net_inflow < 0:
            score -= 12
            notes.append("主力资金净流出，隔夜承接要保守")
    if flow_ratio is not None:
        if flow_ratio >= 0.10:
            score += 8
            notes.append("主力净流入占成交额比例高")
        elif flow_ratio >= 0.05:
            score += 4
        elif flow_ratio <= -0.10:
            score -= 12
            notes.append("主力净流出占成交额比例偏高")
        elif flow_ratio <= -0.05:
            score -= 7

    return max(0, min(100, round(score))), notes


def setup_type(summary, snapshot):
    intraday_close = snapshot.get("intradayClose")
    high_5 = summary.get("high_5")
    ma5 = summary.get("ma5")
    prev_close = snapshot.get("previousClose")
    if None not in (intraday_close, high_5) and intraday_close >= high_5 * 0.99:
        return "突破型"
    if None not in (intraday_close, ma5) and intraday_close >= ma5:
        return "趋势型"
    if None not in (intraday_close, prev_close) and intraday_close >= prev_close:
        return "回踩型"
    return "震荡低吸型"


def build_levels(summary, snapshot):
    intraday_close = snapshot.get("intradayClose")
    intraday_low = snapshot.get("intradayLow")
    intraday_high = snapshot.get("intradayHigh")
    price_1400 = snapshot.get("priceAt1400")
    atr14 = summary.get("atr14") or (intraday_close * 0.02 if intraday_close else None)
    low_5 = summary.get("low_5")
    high_5 = summary.get("high_5")
    high_20 = summary.get("high_20")

    support_candidates = [value for value in (price_1400, intraday_low, low_5) if value is not None]
    support = max(support_candidates) if support_candidates else None
    resistance_candidates = [value for value in (intraday_high, high_5, high_20) if value is not None]
    resistance = min(resistance_candidates) if resistance_candidates else None

    if intraday_close is None:
        return {}

    buffer = atr14 * 0.35 if atr14 is not None else intraday_close * 0.008
    entry_low = round(max(intraday_close - buffer, support or intraday_close), 2)
    entry_high = round(min(intraday_close + buffer, (intraday_high or intraday_close) * 1.002), 2)

    if support is not None:
        stop = round(min(support * 0.99, entry_low - (atr14 * 0.45 if atr14 else intraday_close * 0.01)), 2)
    else:
        stop = round(intraday_close * 0.985, 2)

    if resistance is None or resistance <= entry_high:
        resistance = intraday_close + (atr14 or intraday_close * 0.02)
    t1 = round(max(resistance, entry_high + (atr14 or intraday_close * 0.015)), 2)
    t2 = round(max(t1 + (atr14 or intraday_close * 0.02), t1 * 1.03), 2)

    risk = max(entry_low - stop, 0.01)
    reward = max(t1 - entry_high, 0.01)
    rr = f"1:{min(max(reward / risk, 0.5), 5.0):.1f}"
    return {
        "support": round(support, 2) if support is not None else None,
        "resistance": round(resistance, 2) if resistance is not None else None,
        "entryLow": entry_low,
        "entryHigh": entry_high,
        "stop": stop,
        "target1": t1,
        "target2": t2,
        "riskReward": rr,
    }


def build_row(item, snapshots, market_metrics_map=None):
    rows = item.get("sources", {}).get("10jqka_last") or []
    summary = summarize_rows(rows)
    snapshot = snapshots.get(item.get("ticker"), {})
    metrics = (market_metrics_map or {}).get(item.get("ticker"), {})
    score, notes = score_candidate(summary, snapshot, metrics)
    levels = build_levels(summary, snapshot)

    intraday_close = snapshot.get("intradayClose")
    previous_close = snapshot.get("previousClose")
    row = {
        "ticker": item.get("ticker"),
        "market": item.get("market"),
        "score": score,
        "scoreNotes": notes,
        "setupType": setup_type(summary, snapshot),
        "prevOpen": summary.get("prev_open"),
        "prevClose": summary.get("prev_close"),
        "todayDate": snapshot.get("sessionDate"),
        "latestMinute": snapshot.get("latestMinute"),
        "todayOpen": snapshot.get("intradayOpen"),
        "todayClose": intraday_close,
        "todayHigh": snapshot.get("intradayHigh"),
        "todayLow": snapshot.get("intradayLow"),
        "dayChangePct": pct(previous_close, intraday_close),
        "changeFrom1400Pct": snapshot.get("changeFrom1400Pct"),
        "rangePosition": snapshot.get("rangePosition"),
        "lateVolumeShare": snapshot.get("lateVolumeShare"),
        "buyWindow": "D日 14:50-14:57",
        "sellWindow": "D+1 9:30-10:30 优先处理，弱则更早",
        "holdWindow": "隔夜到次日 1 个交易日为主",
        "coreLogic": "尾盘强于14:00后走势，且主力资金方向支持隔夜博弈" if snapshot.get("changeFrom1400Pct", -99) > 0 and "净流入" in capital_flow_label(metrics) else ("尾盘强于14:00后走势，适合T+1隔夜博弈" if snapshot.get("changeFrom1400Pct", -99) > 0 else "尾盘承接一般，仅适合严格条件低吸"),
        "skipCondition": "高开过多、尾盘回落、流动性骤降或主力资金明显净流出时放弃",
        "nextDayPlan": "高开先止盈一部分，平开看第一目标，低开跌破止损线直接执行保护",
        "summary": summary,
        "marketMetrics": metrics,
        "capitalFlowLabel": capital_flow_label(metrics),
    }
    row.update(levels)
    return row


def main():
    if len(sys.argv) not in (3, 4):
        print("Usage: build_tail_watchlist.py <quotes.json> <intraday_snapshot.json> [market_universe.json]", file=sys.stderr)
        sys.exit(1)
    quotes = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    snapshots = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    market_metrics_map = load_market_metrics(sys.argv[3]) if len(sys.argv) == 4 else {}
    snapshot_map = {item["ticker"]: item for item in snapshots}
    rows = [build_row(item, snapshot_map, market_metrics_map) for item in quotes]
    rows = [row for row in rows if row.get("todayClose") is not None]
    rows.sort(key=lambda row: row["score"], reverse=True)
    out = {
        "tail_entry": rows[:8],
        "notes": [f"{row['ticker']}: score={row['score']} latestMinute={row.get('latestMinute')} netInflow={row.get('marketMetrics', {}).get('netInflow')}" for row in rows[:8]],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
