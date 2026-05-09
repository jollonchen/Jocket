#!/usr/bin/env python3
import json
import re
import sys
import urllib.request
from pathlib import Path
from urllib.error import HTTPError, URLError

UA = "Mozilla/5.0 (OpenClaw Skill a-share-stock-picker)"
TIMEOUT = 12
FIELDS = ("zjjlr", "money", "hsl", "zdf")
PAGES_PER_FIELD = 10
DEFAULT_LIMIT = 200

FIELD_WEIGHT = {
    "zjjlr": 40,
    "money": 30,
    "hsl": 20,
    "zdf": 10,
}


def fetch_text(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Referer": "https://data.10jqka.com.cn/funds/ggzjl/",
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        raw = resp.read()
        for enc in ("gb18030", "gbk", "utf-8", "latin1"):
            try:
                return raw.decode(enc)
            except Exception:
                pass
    return raw.decode("utf-8", errors="ignore")


def clean_text(text):
    text = re.sub(r"<!--.*?-->", "", str(text), flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_number(text):
    if text is None:
        return None
    raw = clean_text(text).replace(",", "").replace("%", "")
    if not raw or raw in {"--", "亏损"}:
        return None
    multiplier = 1.0
    if raw.endswith("亿"):
        multiplier = 100000000.0
        raw = raw[:-1]
    elif raw.endswith("万"):
        multiplier = 10000.0
        raw = raw[:-1]
    elif raw.endswith("元"):
        raw = raw[:-1]
    try:
        return float(raw) * multiplier
    except Exception:
        return None


def market_from_ticker(ticker):
    return "sh" if ticker.startswith(("5", "6", "9")) else "sz"


def eligible_name(name):
    upper = (name or "").upper()
    if not upper or len(upper) < 2:
        return False
    if "ST" in upper:
        return False
    if upper.startswith(("N", "C")):
        return False
    return True


def parse_rows(text):
    tbody = re.search(r"<tbody>(.*?)</tbody>", text, re.S)
    if not tbody:
        return []
    rows = []
    for tr in re.findall(r"<tr.*?>(.*?)</tr>", tbody.group(1), re.S):
        code_match = re.search(r'class="stockCode">(\d{6})</a>', tr)
        name_match = re.search(r'class="J_showCanvas">([^<]+)</a>', tr)
        if not code_match or not name_match:
            continue
        cells = [clean_text(td) for td in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(cells) < 10:
            continue
        ticker = code_match.group(1)
        name = clean_text(name_match.group(1))
        if not eligible_name(name):
            continue
        row = {
            "ticker": ticker,
            "market": market_from_ticker(ticker),
            "name": name,
            "lastPrice": parse_number(cells[3]),
            "chgPct": parse_number(cells[4]),
            "turnoverPct": parse_number(cells[5]),
            "flowIn": parse_number(cells[6]),
            "flowOut": parse_number(cells[7]),
            "netInflow": parse_number(cells[8]),
            "amount": parse_number(cells[9]),
        }
        rows.append(row)
    return rows


def fetch_rank_page(field, page):
    url = f"https://data.10jqka.com.cn/funds/ggzjl/field/{field}/order/desc/page/{page}/"
    text = fetch_text(url)
    return parse_rows(text)


def base_score(row):
    amount = row.get("amount") or 0
    turnover = row.get("turnoverPct") or 0
    net_inflow = row.get("netInflow") or 0
    chg = row.get("chgPct") or 0
    score = 0.0
    if amount >= 3000000000:
        score += 28
    elif amount >= 1500000000:
        score += 22
    elif amount >= 500000000:
        score += 14
    elif amount >= 200000000:
        score += 8

    if 3 <= turnover <= 25:
        score += 18
    elif 1.5 <= turnover < 3:
        score += 10
    elif turnover > 25:
        score += 6

    if net_inflow > 0:
        if net_inflow >= 500000000:
            score += 22
        elif net_inflow >= 100000000:
            score += 14
        else:
            score += 6
    else:
        score -= 6

    if 0 < chg <= 8:
        score += 16
    elif 8 < chg <= 15:
        score += 6
    elif chg < -2:
        score -= 12
    return score


def build_universe(limit=DEFAULT_LIMIT):
    pool = {}
    notes = []
    for field in FIELDS:
        for page in range(1, PAGES_PER_FIELD + 1):
            try:
                rows = fetch_rank_page(field, page)
            except (URLError, HTTPError, TimeoutError, Exception) as exc:
                notes.append(f"{field}-page-{page}: {exc}")
                continue
            if not rows:
                break
            for rank_index, row in enumerate(rows, start=1 + (page - 1) * len(rows)):
                item = pool.setdefault(
                    row["ticker"],
                    {
                        "ticker": row["ticker"],
                        "market": row["market"],
                        "name": row["name"],
                        "metrics": {},
                        "ranks": {},
                        "fieldHits": [],
                        "prefilterScore": 0.0,
                    },
                )
                item["metrics"].update({k: v for k, v in row.items() if k not in {"ticker", "market", "name"}})
                item["ranks"][field] = rank_index
                if field not in item["fieldHits"]:
                    item["fieldHits"].append(field)

    results = []
    for item in pool.values():
        score = base_score(item["metrics"])
        for field, rank_value in item["ranks"].items():
            score += max(0.0, FIELD_WEIGHT[field] * (1.0 - (rank_value - 1) / (PAGES_PER_FIELD * 50)))
        if len(item["fieldHits"]) >= 3:
            score += 10
        elif len(item["fieldHits"]) == 2:
            score += 4
        item["prefilterScore"] = round(score, 2)
        results.append(item)

    results.sort(
        key=lambda item: (
            -item["prefilterScore"],
            -(item["metrics"].get("amount") or 0),
            -(item["metrics"].get("turnoverPct") or 0),
            item["ticker"],
        )
    )
    return {
        "limit": limit,
        "fieldPages": PAGES_PER_FIELD,
        "fields": list(FIELDS),
        "count": min(limit, len(results)),
        "universe": results[:limit],
        "notes": notes,
    }


def main():
    limit = DEFAULT_LIMIT
    if len(sys.argv) == 2:
        limit = int(sys.argv[1])
    elif len(sys.argv) > 2:
        print("Usage: fetch_market_universe.py [limit]", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(build_universe(limit), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
