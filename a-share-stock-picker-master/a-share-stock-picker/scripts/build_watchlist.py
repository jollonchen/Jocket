#!/usr/bin/env python3
import json
import sys
from pathlib import Path

DEFAULT_BUCKET_COUNT = 5


def load_market_metrics(path):
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding='utf-8'))
    return {item['ticker']: item.get('metrics', {}) for item in data.get('universe', []) if item.get('ticker')}


def to_float(v):
    try:
        return float(v)
    except Exception:
        return None


def pct(a, b):
    if a in (None, 0) or b is None:
        return None
    return (b - a) / a * 100.0


def capital_flow_ratio(metrics):
    net_inflow = to_float(metrics.get('netInflow'))
    amount = to_float(metrics.get('amount'))
    if net_inflow is None or amount in (None, 0):
        return None
    return net_inflow / amount


def capital_flow_label(metrics):
    net_inflow = to_float(metrics.get('netInflow'))
    ratio = capital_flow_ratio(metrics)
    if net_inflow is None:
        return '待确认'
    if net_inflow >= 500_000_000 or (ratio is not None and ratio >= 0.08):
        return '主力净流入较强'
    if net_inflow >= 100_000_000 or (ratio is not None and ratio >= 0.03):
        return '主力净流入为正'
    if net_inflow <= -500_000_000 or (ratio is not None and ratio <= -0.08):
        return '主力净流出较强'
    if net_inflow < 0:
        return '主力净流出'
    return '主力资金中性'


def summarize_rows(rows):
    if not rows:
        return {}
    closes = [to_float(r.get('close')) for r in rows if to_float(r.get('close')) is not None]
    highs = [to_float(r.get('high')) for r in rows if to_float(r.get('high')) is not None]
    lows = [to_float(r.get('low')) for r in rows if to_float(r.get('low')) is not None]
    vols = [to_float(r.get('volume')) for r in rows if to_float(r.get('volume')) is not None]
    if not closes:
        return {}
    last_close = closes[-1]
    prev_close = closes[-2] if len(closes) >= 2 else None
    return {
        'last_close': last_close,
        'prev_close': prev_close,
        'chg_1d': pct(prev_close, last_close) if prev_close is not None else None,
        'high_5': max(highs[-5:]) if highs else None,
        'low_5': min(lows[-5:]) if lows else None,
        'high_20': max(highs[-20:]) if highs else (max(highs) if highs else None),
        'low_20': min(lows[-20:]) if lows else (min(lows) if lows else None),
        'avg_vol_5': sum(vols[-5:]) / len(vols[-5:]) if len(vols) >= 5 else (sum(vols) / len(vols) if vols else None),
        'rows': len(rows),
    }


def score_bucket(summary, status, market_metrics=None):
    short = 40
    medium = 45
    long = 50
    if status == 'verified':
        short += 10; medium += 10; long += 10
    chg = summary.get('chg_1d')
    if chg is not None:
        if 0 < chg < 4:
            short += 12; medium += 8
        elif chg >= 4:
            short += 6; medium += 4
        elif chg < 0:
            short -= 6; medium -= 4
    rows = summary.get('rows', 0)
    if rows >= 20:
        medium += 10; long += 8
    if rows >= 60:
        long += 10
    last_close = summary.get('last_close')
    high_20 = summary.get('high_20')
    low_20 = summary.get('low_20')
    high_5 = summary.get('high_5')
    low_5 = summary.get('low_5')
    if None not in (last_close, high_20, low_20) and high_20 != low_20:
        pos20 = (last_close - low_20) / (high_20 - low_20)
        if pos20 > 0.7:
            short += 8; medium += 8
        elif pos20 < 0.3:
            long += 4
    if None not in (last_close, high_5, low_5) and high_5 != low_5:
        pos5 = (last_close - low_5) / (high_5 - low_5)
        if pos5 > 0.8:
            short += 10

    metrics = market_metrics or {}
    net_inflow = to_float(metrics.get('netInflow'))
    amount = to_float(metrics.get('amount'))
    turnover = to_float(metrics.get('turnoverPct'))
    flow_ratio = capital_flow_ratio(metrics)
    if amount is not None:
        if amount >= 3_000_000_000:
            short += 8
            medium += 6
        elif amount >= 1_000_000_000:
            short += 4
            medium += 3
    if turnover is not None:
        if 3 <= turnover <= 20:
            short += 6
            medium += 4
        elif turnover > 25:
            short += 2
            medium -= 2
    if net_inflow is not None:
        if net_inflow >= 500_000_000:
            short += 12
            medium += 10
            long += 5
        elif net_inflow >= 100_000_000:
            short += 8
            medium += 6
            long += 2
        elif net_inflow < 0:
            short -= 10
            medium -= 7
            long -= 3
    if flow_ratio is not None:
        if flow_ratio >= 0.10:
            short += 8
            medium += 6
        elif flow_ratio >= 0.05:
            short += 5
            medium += 4
        elif flow_ratio <= -0.10:
            short -= 12
            medium -= 8
            long -= 4
        elif flow_ratio <= -0.05:
            short -= 7
            medium -= 5
    return {
        'short': max(0, min(100, round(short))),
        'medium': max(0, min(100, round(medium))),
        'long': max(0, min(100, round(long))),
    }


def primary_horizon(scores, summary, market_metrics=None):
    chg = summary.get('chg_1d')
    flow_label = capital_flow_label(market_metrics or {})
    if chg is not None and chg > 1.5 and scores['short'] >= scores['medium'] - 2:
        if '净流出' in flow_label and scores['medium'] >= scores['short'] - 3:
            return 'medium'
        return 'short'
    if scores['long'] >= scores['medium'] and scores['long'] >= scores['short']:
        return 'long'
    if scores['medium'] >= scores['short']:
        return 'medium'
    return 'short'


def build_row(item, market_metrics_map=None):
    data = item.get('sources', {})
    last_rows = data.get('10jqka_last') or []
    anchor = data.get('10jqka_today') or {}
    status = 'verified' if last_rows or anchor else 'fallback-only'
    summary = summarize_rows(last_rows)
    metrics = (market_metrics_map or {}).get(item.get('ticker'), {})
    scores = score_bucket(summary, status, metrics)
    primary = primary_horizon(scores, summary, metrics)
    row = {
        'ticker': item.get('ticker'),
        'market': item.get('market'),
        'anchorDate': anchor.get('date') if isinstance(anchor, dict) else None,
        'open': anchor.get('open') if isinstance(anchor, dict) and anchor.get('open') else (last_rows[-1].get('open') if last_rows else None),
        'close': anchor.get('close') if isinstance(anchor, dict) and anchor.get('close') else (last_rows[-1].get('close') if last_rows else None),
        'status': status,
        'scores': scores,
        'primaryHorizon': primary,
        'summary': summary,
        'marketMetrics': metrics,
        'capitalFlowLabel': capital_flow_label(metrics),
        'plan': '条件观察' if status != 'verified' else '可进一步细化',
    }
    return row


def ensure_minimum_buckets(out, rows):
    for bucket in ('short', 'medium', 'long'):
        if len(out[bucket]) >= DEFAULT_BUCKET_COUNT:
            continue
        sorted_rows = sorted(rows, key=lambda r: r['scores'][bucket], reverse=True)
        for row in sorted_rows:
            if row not in out[bucket]:
                out[bucket].append(row)
            if len(out[bucket]) >= DEFAULT_BUCKET_COUNT:
                break


def main():
    if len(sys.argv) not in (2, 3):
        print('Usage: build_watchlist.py <quotes.json> [market_universe.json]', file=sys.stderr)
        sys.exit(1)
    data = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    market_metrics_map = load_market_metrics(sys.argv[2]) if len(sys.argv) == 3 else {}
    out = {'short': [], 'medium': [], 'long': [], 'notes': []}
    rows = [build_row(item, market_metrics_map) for item in data]
    for row in rows:
        out[row['primaryHorizon']].append(row)
        net_inflow = row.get('marketMetrics', {}).get('netInflow')
        out['notes'].append(f"{row['ticker']}: short={row['scores']['short']} medium={row['scores']['medium']} long={row['scores']['long']} status={row['status']} netInflow={net_inflow}")
    ensure_minimum_buckets(out, rows)
    for key in ('short','medium','long'):
        out[key] = sorted(out[key], key=lambda r: r['scores'][key], reverse=True)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
