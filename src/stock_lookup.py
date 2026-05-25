from __future__ import annotations

from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
import re

import pandas as pd
import requests

from .universe import DEFAULT_UNIVERSE
from .utils import display_code, normalize_a_share_code

try:
    import akshare as ak
except Exception:  # pragma: no cover
    ak = None

LOCAL_PRIORITY_STOCKS = [
    ("润建股份", "002929"),
]


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
    df = pd.DataFrame(DEFAULT_UNIVERSE + LOCAL_PRIORITY_STOCKS, columns=["name", "code"])
    df["source"] = "default"
    return df


def _directory_cache_path() -> Path:
    path = Path("data/cache/profile/stock_directory.csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _directory_from_cache(ttl_seconds: int = 7 * 24 * 3600) -> pd.DataFrame:
    path = _directory_cache_path()
    if not path.exists() or (datetime.now().timestamp() - path.stat().st_mtime) > ttl_seconds:
        return pd.DataFrame(columns=["name", "code", "source"])
    try:
        df = pd.read_csv(path, dtype={"code": str})
    except Exception:
        return pd.DataFrame(columns=["name", "code", "source"])
    keep = [col for col in ["name", "code", "source"] if col in df.columns]
    return df[keep].copy() if {"name", "code"}.issubset(keep) else pd.DataFrame(columns=["name", "code", "source"])


def _directory_from_akshare() -> pd.DataFrame:
    if ak is None:
        return pd.DataFrame(columns=["name", "code", "source"])
    try:
        # A-share spot
        df_a = ak.stock_zh_a_spot_em()
        # HK spot
        df_hk = ak.stock_hk_spot_em()
    except Exception:
        return pd.DataFrame(columns=["name", "code", "source"])
        
    frames = []
    if df_a is not None and not df_a.empty:
        a_out = df_a[["名称", "代码"]].rename(columns={"名称": "name", "代码": "code"}).copy()
        a_out["source"] = "akshare_a"
        frames.append(a_out)
    if df_hk is not None and not df_hk.empty:
        hk_out = df_hk[["名称", "代码"]].rename(columns={"名称": "name", "代码": "code"}).copy()
        hk_out["source"] = "akshare_hk"
        frames.append(hk_out)
        
    if not frames:
        return pd.DataFrame(columns=["name", "code", "source"])
    return pd.concat(frames, ignore_index=True)


def build_stock_directory(include_remote: bool = False) -> pd.DataFrame:
    frames = [_directory_from_default(), _directory_from_cache()]
    if include_remote:
        remote = _directory_from_akshare()
        if remote is not None and not remote.empty:
            try:
                remote.to_csv(_directory_cache_path(), index=False, encoding="utf-8-sig")
            except Exception:
                pass
            frames.append(remote)
    out = pd.concat(frames, ignore_index=True)
    out["name"] = out["name"].astype(str).str.strip()
    out["code"] = out["code"].astype(str).str.strip()
    out = out.dropna(subset=["code"]).drop_duplicates("code", keep="last")
    out["yahoo_code"] = out["code"].map(normalize_a_share_code)
    out["display_code"] = out["yahoo_code"].map(display_code)
    out["query_name"] = out["name"].map(_clean_query)
    return out.sort_values(["source", "display_code"]).reset_index(drop=True)


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
        # Allow A-share, HK, and US
        if classify not in ("AStock", "HKStock", "USStock"):
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


def resolve_stock_query(query: str, directory: pd.DataFrame, limit: int = 8, include_remote_suggest: bool = True) -> list[dict]:
    raw = str(query or "").strip()
    clean = _clean_query(raw)
    if not clean:
        return []

    # Match A-share or HK-share codes
    code_match = re.search(r"\b\d{5,6}\b", clean)
    # Or match US tickers (if alphanumeric and STRICTLY ASCII)
    if not code_match and clean.isascii() and clean.isalpha():
        code = clean
    else:
        code = code_match.group(0) if code_match else clean
        
    rows: list[dict] = []
    
    # ... (existing add_row logic remains same, but resolve_stock_query body changes)
    def add_row(row: pd.Series | dict, score: float, reason: str) -> None:
        item = row.to_dict() if isinstance(row, pd.Series) else dict(row)
        item["code"] = display_code(str(item.get("code") or item.get("yahoo_code") or ""))
        item["score"] = score
        item["reason"] = reason
        rows.append(item)

    directory = directory.copy()
    if "display_code" not in directory.columns:
        directory["display_code"] = directory["code"].astype(str).map(lambda value: display_code(normalize_a_share_code(value)))
    if "query_name" not in directory.columns:
        directory["query_name"] = directory["name"].map(_clean_query)

    # 1. Exact code match in directory
    exact_code = directory[directory["display_code"].astype(str) == code]
    if not exact_code.empty:
        add_row(exact_code.iloc[0], 1.2, "代码精确匹配")

    # 2. Exact name match
    exact_name = directory[directory["query_name"] == clean]
    for _, row in exact_name.iterrows():
        add_row(row, 1.1, "名称精确匹配")

    # 3. Contains match
    contains = directory[
        directory["query_name"].str.contains(re.escape(clean), na=False)
        | directory["display_code"].astype(str).str.startswith(clean, na=False)
    ]
    for _, row in contains.head(limit * 2).iterrows():
        add_row(row, 0.95, "名称/代码包含匹配")

    # 4. Remote suggest only when local data is missing, keeping typing responsive.
    if include_remote_suggest and not rows:
        for item in _suggest_remote(raw, limit):
            add_row(item, float(item.get("score", 1.0)), str(item.get("reason") or "远程检索"))

    if not rows and re.fullmatch(r"(\d{5,6}|[A-Z]+)", code):
        add_row({"name": code, "code": code, "source": "manual", "yahoo_code": normalize_a_share_code(code)}, 0.7, "代码格式有效")

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
