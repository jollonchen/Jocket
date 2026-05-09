#!/usr/bin/env python3
import json
import sys
from pathlib import Path


def to_float(v):
    try:
        return float(v)
    except Exception:
        return None


def sma(vals, n):
    if len(vals) < n or n <= 0:
        return None
    arr = vals[-n:]
    return sum(arr) / len(arr)


def ema(vals, n):
    if not vals:
        return None
    k = 2 / (n + 1)
    cur = vals[0]
    for v in vals[1:]:
        cur = v * k + cur * (1 - k)
    return cur


def atr(rows, n=14):
    if len(rows) < 2:
        return None
    trs = []
    prev_close = to_float(rows[0].get('close'))
    for r in rows[1:]:
        h, l, c = to_float(r.get('high')), to_float(r.get('low')), to_float(r.get('close'))
        if None in (h, l, c, prev_close):
            prev_close = c
            continue
        tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        trs.append(tr)
        prev_close = c
    if len(trs) < n:
        return sum(trs) / len(trs) if trs else None
    return sum(trs[-n:]) / n


def macd(vals):
    if len(vals) < 26:
        return None
    ema12 = ema(vals[-60:] if len(vals) > 60 else vals, 12)
    ema26 = ema(vals[-60:] if len(vals) > 60 else vals, 26)
    if ema12 is None or ema26 is None:
        return None
    dif = ema12 - ema26
    return {'dif': round(dif, 4)}


def main():
    if len(sys.argv) != 2:
        print('Usage: indicators.py <quotes.json>', file=sys.stderr)
        sys.exit(1)
    data = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    out = []
    for item in data:
        rows = item.get('sources', {}).get('10jqka_last') or []
        closes = [to_float(r.get('close')) for r in rows if to_float(r.get('close')) is not None]
        vols = [to_float(r.get('volume')) for r in rows if to_float(r.get('volume')) is not None]
        last_vol = vols[-1] if vols else None
        avg_vol_5 = sum(vols[-5:]) / len(vols[-5:]) if len(vols) >= 5 else (sum(vols) / len(vols) if vols else None)
        vol_ratio = (last_vol / avg_vol_5) if last_vol and avg_vol_5 else None
        out.append({
            'ticker': item.get('ticker'),
            'ma5': sma(closes, 5),
            'ma20': sma(closes, 20),
            'ma60': sma(closes, 60),
            'atr14': atr(rows, 14),
            'macd': macd(closes),
            'vol_ratio': round(vol_ratio, 3) if vol_ratio is not None else None,
        })
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
