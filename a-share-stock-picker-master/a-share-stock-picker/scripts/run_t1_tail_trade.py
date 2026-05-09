#!/usr/bin/env python3
import json
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent


def run(cmd, outfile):
    with open(outfile, "w", encoding="utf-8") as handle:
        subprocess.run(cmd, check=True, stdout=handle)


def load_market_pool(path, detail_limit=200):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [item["ticker"] for item in data.get("universe", [])[:detail_limit]]


def final_tail_tickers(path, limit=5):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [row["ticker"] for row in data.get("tail_entry", [])[:limit] if row.get("ticker")]


def main():
    tickers = [ticker[-6:] for ticker in sys.argv[1:]]
    work = Path.cwd()
    market_pool = work / "market_universe.json"
    quotes = work / "tail_quotes.json"
    snapshot = work / "intraday_snapshot.json"
    watchlist = work / "tail_watchlist.json"
    context = work / "tail_ths_context.json"
    report = work / "t1_tail_plan.md"

    if tickers:
        analysis_tickers = tickers
    else:
        run(["python3", str(BASE / "fetch_market_universe.py"), "200"], market_pool)
        analysis_tickers = load_market_pool(market_pool, detail_limit=200)
        if not analysis_tickers:
            raise SystemExit("No market universe candidates fetched")

    run(["python3", str(BASE / "fetch_quotes.py"), *analysis_tickers], quotes)
    run(["python3", str(BASE / "fetch_intraday_snapshot.py"), str(quotes)], snapshot)
    build_cmd = ["python3", str(BASE / "build_tail_watchlist.py"), str(quotes), str(snapshot)]
    if market_pool.exists():
        build_cmd.append(str(market_pool))
    run(build_cmd, watchlist)
    run(["python3", str(BASE / "fetch_ths_context.py"), *final_tail_tickers(watchlist, limit=5)], context)
    run(["python3", str(BASE / "render_t1_plan.py"), str(watchlist), str(context), str(context)], report)

    print(
        json.dumps(
            {
                "market_universe": str(market_pool) if not tickers else None,
                "quotes": str(quotes),
                "intraday_snapshot": str(snapshot),
                "tail_watchlist": str(watchlist),
                "ths_context": str(context),
                "catalysts": str(context),
                "news_summary": str(context),
                "report": str(report),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
