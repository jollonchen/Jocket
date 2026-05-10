from __future__ import annotations

from difflib import SequenceMatcher
import re

import pandas as pd
import requests

from .universe import DEFAULT_UNIVERSE
from .utils import display_code, normalize_a_share_code


def _request_json(url: str, **kwargs) -> dict:
    try:
        resp = requests.get(url, **kwargs)
    except Exception:
        session = requests.Session()
        session.trust_env = False
        resp = session.get(url, **kwargs)
    resp.raise_for_status()
    return resp.json()


def _clean_query(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def _directory_from_default() -> pd.DataFrame:
    df = pd.DataFrame(DEFAULT_UNIVERSE, columns=["name", "code"])
    df["source"] = "default"
    return df


def build_stock_directory() -> pd.DataFrame:
    frames = [_directory_from_default()]

    out = pd.concat(frames, ignore_index=True)
    out["code"] = out["code"].astype(str).str.extract(r"(\d{6})", expand=False)
    out["name"] = out["name"].astype(str).str.strip()
    out = out.dropna(subset=["code"]).drop_duplicates("code", keep="last")
    out["yahoo_code"] = out["code"].map(normalize_a_share_code)
    out["query_name"] = out["name"].map(_clean_query)
    return out.sort_values(["source", "code"]).reset_index(drop=True)


def _suggest_remote(query: str, limit: int) -> list[dict]:
    try:
        payload = _request_json(
            "https://searchapi.eastmoney.com/api/suggest/get",
            params={"input": query, "type": 14, "count": limit},
            headers={"User-Agent": "Mozilla/5.0 (stock-picker-ui)"},
            timeout=5,
        )
    except Exception:
        return []

    rows = ((payload.get("QuotationCodeTable") or {}).get("Data") or [])
    out = []
    for item in rows:
        classify = str(item.get("Classify") or "")
        code = str(item.get("Code") or item.get("UnifiedCode") or "")
        name = str(item.get("Name") or "")
        if classify and classify != "AStock":
            continue
        if not re.fullmatch(r"\d{6}", code):
            continue
        out.append(
            {
                "name": name,
                "code": code,
                "source": "eastmoney_suggest",
                "yahoo_code": normalize_a_share_code(code),
                "score": 1.0,
                "reason": "远程名称/代码检索",
            }
        )
    return out


def resolve_stock_query(query: str, directory: pd.DataFrame, limit: int = 8) -> list[dict]:
    raw = str(query or "").strip()
    clean = _clean_query(raw)
    if not clean:
        return []

    code_match = re.search(r"\d{6}", clean)
    code = code_match.group(0) if code_match else display_code(normalize_a_share_code(clean))
    rows: list[dict] = []

    def add_row(row: pd.Series | dict, score: float, reason: str) -> None:
        item = row.to_dict() if isinstance(row, pd.Series) else dict(row)
        item["code"] = display_code(str(item.get("code") or item.get("yahoo_code") or ""))
        item["score"] = score
        item["reason"] = reason
        rows.append(item)

    if re.fullmatch(r"\d{6}", code):
        exact_code = directory[directory["code"] == code]
        if not exact_code.empty:
            add_row(exact_code.iloc[0], 1.2, "代码精确匹配")
        else:
            add_row({"name": code, "code": code, "source": "manual", "yahoo_code": normalize_a_share_code(code)}, 1.0, "代码格式有效")

    exact_name = directory[directory["query_name"] == clean]
    for _, row in exact_name.iterrows():
        add_row(row, 1.1, "名称精确匹配")

    contains = directory[
        directory["query_name"].str.contains(re.escape(clean), na=False)
        | directory["code"].str.startswith(clean, na=False)
    ]
    for _, row in contains.head(limit * 2).iterrows():
        add_row(row, 0.95, "名称/代码包含匹配")

    if not rows:
        for item in _suggest_remote(raw, limit):
            add_row(item, float(item.get("score", 1.0)), str(item.get("reason") or "远程检索"))

    if len(rows) < limit:
        scored = []
        for _, row in directory.iterrows():
            name = str(row.get("query_name") or "")
            if not name:
                continue
            ratio = SequenceMatcher(None, clean, name).ratio()
            if ratio >= 0.34:
                scored.append((ratio, row))
        for ratio, row in sorted(scored, key=lambda x: x[0], reverse=True)[: limit * 2]:
            add_row(row, ratio, "名称模糊匹配")

    deduped: dict[str, dict] = {}
    for item in rows:
        item_code = str(item.get("code") or "")
        if not item_code:
            continue
        if item_code not in deduped or float(item.get("score", 0)) > float(deduped[item_code].get("score", 0)):
            deduped[item_code] = item

    return sorted(deduped.values(), key=lambda x: float(x.get("score", 0)), reverse=True)[:limit]
