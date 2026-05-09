#!/usr/bin/env python3
import json
import sys
from pathlib import Path


def to_float(value):
    try:
        return float(value)
    except Exception:
        return None


def pct(base, current):
    if base in (None, 0) or current is None:
        return None
    return (current - base) / base * 100.0


def parse_time_rows(item):
    time_data = item.get("sources", {}).get("10jqka_time") or {}
    raw_rows = time_data.get("data") or []
    rows = []
    for raw in raw_rows:
        parts = raw.split(",")
        if len(parts) < 5:
            continue
        rows.append(
            {
                "time": parts[0],
                "price": to_float(parts[1]),
                "volume": to_float(parts[2]),
                "avg_price": to_float(parts[3]),
                "amount": to_float(parts[4]),
            }
        )
    return time_data, rows


def first_at_or_after(rows, hhmm):
    for row in rows:
        if row["time"] >= hhmm:
            return row
    return rows[-1] if rows else None


def summarize_item(item):
    time_data, rows = parse_time_rows(item)
    if not rows:
        return {
            "ticker": item.get("ticker"),
            "market": item.get("market"),
            "status": "missing_intraday",
        }

    prices = [row["price"] for row in rows if row["price"] is not None]
    day_volume = sum(row["volume"] or 0 for row in rows)
    day_amount = sum(row["amount"] or 0 for row in rows)
    after_1400 = [row for row in rows if row["time"] >= "1400"]
    after_1430 = [row for row in rows if row["time"] >= "1430"]
    ref_1400 = first_at_or_after(rows, "1400")
    ref_1430 = first_at_or_after(rows, "1430")
    last_row = rows[-1]

    intraday_open = rows[0]["price"]
    intraday_close = last_row["price"]
    intraday_high = max(prices) if prices else None
    intraday_low = min(prices) if prices else None
    range_position = None
    if None not in (intraday_close, intraday_high, intraday_low) and intraday_high != intraday_low:
        range_position = (intraday_close - intraday_low) / (intraday_high - intraday_low)

    late_volume = sum(row["volume"] or 0 for row in after_1400)
    late_amount = sum(row["amount"] or 0 for row in after_1400)
    last30_volume = sum(row["volume"] or 0 for row in after_1430)
    last30_amount = sum(row["amount"] or 0 for row in after_1430)

    return {
        "ticker": item.get("ticker"),
        "market": item.get("market"),
        "status": "verified",
        "sessionDate": time_data.get("date"),
        "previousClose": to_float(time_data.get("pre")),
        "latestMinute": last_row["time"],
        "intradayOpen": intraday_open,
        "intradayClose": intraday_close,
        "intradayHigh": intraday_high,
        "intradayLow": intraday_low,
        "priceAt1400": ref_1400["price"] if ref_1400 else None,
        "priceAt1430": ref_1430["price"] if ref_1430 else None,
        "changeFromPrevClosePct": pct(to_float(time_data.get("pre")), intraday_close),
        "changeFrom1400Pct": pct(ref_1400["price"] if ref_1400 else None, intraday_close),
        "changeFrom1430Pct": pct(ref_1430["price"] if ref_1430 else None, intraday_close),
        "rangePosition": range_position,
        "lateVolumeShare": (late_volume / day_volume) if day_volume else None,
        "lateAmountShare": (late_amount / day_amount) if day_amount else None,
        "last30VolumeShare": (last30_volume / day_volume) if day_volume else None,
        "last30AmountShare": (last30_amount / day_amount) if day_amount else None,
    }


def main():
    if len(sys.argv) != 2:
        print("Usage: fetch_intraday_snapshot.py <quotes.json>", file=sys.stderr)
        sys.exit(1)
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = [summarize_item(item) for item in data]
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
