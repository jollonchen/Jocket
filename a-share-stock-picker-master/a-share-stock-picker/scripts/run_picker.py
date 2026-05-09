#!/usr/bin/env python3
import json
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
DEFAULT_BUCKET_COUNT = 5


def run(cmd, outfile):
    with open(outfile, 'w', encoding='utf-8') as f:
        subprocess.run(cmd, check=True, stdout=f)


def load_market_pool(path, detail_limit=200):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    return [item['ticker'] for item in data.get('universe', [])[:detail_limit]]


def final_report_tickers(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    tickers = []
    for bucket in ('short', 'medium', 'long'):
        for row in data.get(bucket, [])[:DEFAULT_BUCKET_COUNT]:
            ticker = row.get('ticker')
            if ticker and ticker not in tickers:
                tickers.append(ticker)
    return tickers


def main():
    tickers = sys.argv[1:]
    work = Path.cwd()
    market_pool = work / 'market_universe.json'
    quotes = work / 'quotes.json'
    watchlist = work / 'watchlist.json'
    context = work / 'ths_context.json'
    indicators = work / 'indicators.json'
    report = work / 'report.md'
    if tickers:
        analysis_tickers = tickers
    else:
        run(['python3', str(BASE / 'fetch_market_universe.py'), '200'], market_pool)
        analysis_tickers = load_market_pool(market_pool, detail_limit=200)
        if not analysis_tickers:
            raise SystemExit('No market universe candidates fetched')
    run(['python3', str(BASE / 'fetch_quotes.py'), *analysis_tickers], quotes)
    build_cmd = ['python3', str(BASE / 'build_watchlist.py'), str(quotes)]
    if market_pool.exists():
        build_cmd.append(str(market_pool))
    run(build_cmd, watchlist)
    report_tickers = final_report_tickers(watchlist)
    run(['python3', str(BASE / 'fetch_ths_context.py'), *[t[-6:] for t in report_tickers]], context)
    run(['python3', str(BASE / 'indicators.py'), str(quotes)], indicators)
    run(['python3', str(BASE / 'render_report.py'), str(watchlist), str(context), str(indicators), str(context)], report)
    print(json.dumps({
        'market_universe': str(market_pool) if not tickers else None,
        'quotes': str(quotes),
        'watchlist': str(watchlist),
        'ths_context': str(context),
        'catalysts': str(context),
        'indicators': str(indicators),
        'news_summary': str(context),
        'report': str(report)
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
