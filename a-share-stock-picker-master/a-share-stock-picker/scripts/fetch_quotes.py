#!/usr/bin/env python3
import json
import re
import sys
import time
import urllib.request
from urllib.error import URLError, HTTPError

UA = "Mozilla/5.0 (OpenClaw Skill a-share-stock-picker)"
TIMEOUT = 12

SOURCES = {
    "10jqka_today": "https://d.10jqka.com.cn/v2/line/{market}_{ticker}/01/today.js",
    "10jqka_last": "https://d.10jqka.com.cn/v2/line/{market}_{ticker}/01/last.js",
    "10jqka_time": "https://d.10jqka.com.cn/v6/time/hs_{ticker}/defer/last.js",
    "eastmoney_quote": "https://quote.eastmoney.com/{secid}.html",
    "sina_quote": "https://finance.sina.com.cn/realstock/company/{marketlc}{ticker}/nc.shtml",
}


def secid(market, ticker):
    return ("1." if market == "sh" else "0.") + ticker


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://www.google.com/"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def parse_today_js(text):
    m = re.search(r'"data":"([^"]+)"', text)
    if m:
        fields = m.group(1).split(',')
        if len(fields) >= 7:
            return {
                "date": fields[0],
                "open": fields[1],
                "high": fields[2],
                "low": fields[3],
                "close": fields[4],
                "volume": fields[5] if len(fields) > 5 else None,
                "amount": fields[6] if len(fields) > 6 else None,
                "raw": fields,
            }
    payload_match = re.search(r'\(\{".+?":(\{.+\})\}\)', text)
    if not payload_match:
        return None
    try:
        payload = json.loads(payload_match.group(1))
    except Exception:
        return None
    return {
        "date": payload.get("1"),
        "open": payload.get("7"),
        "high": payload.get("8"),
        "low": payload.get("9"),
        "close": payload.get("11"),
        "volume": payload.get("13"),
        "amount": payload.get("19"),
        "turnover": payload.get("1968584"),
        "dt": payload.get("dt"),
        "name": payload.get("name"),
        "raw": payload,
    }


def parse_last_js(text):
    m = re.search(r'"data":"([^"]+)"', text)
    if not m:
        return None
    rows = m.group(1).split(';')
    parsed = []
    for row in rows:
        parts = row.split(',')
        if len(parts) >= 5 and parts[0].isdigit():
            parsed.append({
                "date": parts[0],
                "open": parts[1],
                "high": parts[2],
                "low": parts[3],
                "close": parts[4],
                "volume": parts[5] if len(parts) > 5 else None,
                "amount": parts[6] if len(parts) > 6 else None,
                "turnover": parts[7] if len(parts) > 7 else None,
                "raw": parts,
            })
    return parsed or None


def parse_time_js(text):
    out = {}
    m_pre = re.search(r'"pre":"?([0-9.]+)"?', text)
    m_date = re.search(r'"date":"?(\d{8})"?', text)
    m_data = re.search(r'"data":"([^"]+)"', text)
    if m_pre:
        out["pre"] = m_pre.group(1)
    if m_date:
        out["date"] = m_date.group(1)
    if m_data:
        out["data"] = m_data.group(1).split(';')
    return out or None


def try_sources(market, ticker):
    out = {"ticker": ticker, "market": market, "fetchedAt": int(time.time()), "sources": {}, "errors": {}}
    jobs = [
        ("10jqka_today", SOURCES["10jqka_today"].format(market=market, ticker=ticker), parse_today_js),
        ("10jqka_last", SOURCES["10jqka_last"].format(market=market, ticker=ticker), parse_last_js),
        ("10jqka_time", SOURCES["10jqka_time"].format(ticker=ticker), parse_time_js),
        ("eastmoney_quote", SOURCES["eastmoney_quote"].format(secid=secid(market, ticker)), None),
        ("sina_quote", SOURCES["sina_quote"].format(marketlc=market, ticker=ticker), None),
    ]
    for name, url, parser in jobs:
        try:
            text = fetch(url)
            out["sources"][name] = parser(text) if parser else {"ok": True, "url": url, "sample": text[:300]}
        except (URLError, HTTPError, TimeoutError, Exception) as e:
            out["errors"][name] = str(e)
    return out


def main():
    if len(sys.argv) < 2:
        print("Usage: fetch_quotes.py <ticker> [ticker... or sh600000/sz000001]", file=sys.stderr)
        sys.exit(1)
    results = []
    for arg in sys.argv[1:]:
        arg = arg.strip().lower()
        if arg.startswith('sh') or arg.startswith('sz'):
            market, ticker = arg[:2], arg[2:]
        else:
            ticker = arg
            market = 'sh' if ticker.startswith(('6','9','5')) else 'sz'
        results.append(try_sources(market, ticker))
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
