from __future__ import annotations

import html
import re
from io import StringIO
from pathlib import Path

import pandas as pd
import requests
import urllib3

from .cache_utils import FileCache, safe_fetch
from .data_fetcher import _disable_process_proxies
from .utils import ensure_dirs

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
_disable_process_proxies()

try:
    import efinance as ef
except Exception:  # pragma: no cover
    ef = None

try:
    import akshare as ak
except Exception:  # pragma: no cover
    ak = None


def _num(value):
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _normalize_belong_board(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    rename = {
        "股票名称": "stock_name",
        "股票代码": "stock_code",
        "板块代码": "board_code",
        "板块名称": "board_name",
        "板块涨幅": "board_pct",
    }
    view = df.rename(columns=rename).copy()
    keep = [col for col in ["stock_name", "stock_code", "board_code", "board_name", "board_pct"] if col in view.columns]
    view = view[keep]
    if "board_pct" in view.columns:
        view["board_pct"] = pd.to_numeric(view["board_pct"], errors="coerce")
    view["source"] = "efinance"
    return view


def _board_frame(names: list[str], source: str, *, stock_code: str | None = None, board_type: str | None = None) -> pd.DataFrame:
    rows = []
    seen = set()
    for name in names:
        clean = str(name or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        rows.append(
            {
                "stock_code": stock_code,
                "board_name": clean,
                "board_type": board_type,
                "source": source,
            }
        )
    return pd.DataFrame(rows)


def _normalize_flow(df: pd.DataFrame, source: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    rename = {
        "行业": "board_name",
        "行业-涨跌幅": "flow_pct",
        "净额": "net_flow",
        "公司家数": "member_count",
        "领涨股": "leader",
        "领涨股-涨跌幅": "leader_pct",
    }
    view = df.rename(columns=rename).copy()
    keep = [col for col in ["board_name", "flow_pct", "net_flow", "member_count", "leader", "leader_pct"] if col in view.columns]
    view = view[keep]
    for col in ["flow_pct", "net_flow", "leader_pct"]:
        if col in view.columns:
            view[col] = pd.to_numeric(view[col], errors="coerce")
    view["source"] = source
    return view


def _normalize_ak_board_market(df: pd.DataFrame, source: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    rename = {
        "板块代码": "board_code",
        "代码": "board_code",
        "板块名称": "board_name",
        "名称": "board_name",
        "涨跌幅": "board_pct",
        "最新价": "board_price",
        "成交额": "amount",
        "换手率": "turnover_rate",
        "上涨家数": "up_count",
        "下跌家数": "down_count",
        "领涨股票": "leader",
        "领涨股": "leader",
        "领涨股票-涨跌幅": "leader_pct",
        "领涨股-涨跌幅": "leader_pct",
    }
    view = df.rename(columns=rename).copy()
    keep = [
        col
        for col in [
            "board_code",
            "board_name",
            "board_pct",
            "board_price",
            "amount",
            "turnover_rate",
            "up_count",
            "down_count",
            "leader",
            "leader_pct",
        ]
        if col in view.columns
    ]
    view = view[keep]
    for col in ["board_pct", "board_price", "amount", "turnover_rate", "up_count", "down_count", "leader_pct"]:
        if col in view.columns:
            view[col] = pd.to_numeric(view[col], errors="coerce")
    view["source"] = source
    return view


class SectorFetcher:
    """Fetch A-share board / concept membership and market heat with safe fallbacks."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        ensure_dirs()
        Path("data/fundamentals").mkdir(parents=True, exist_ok=True)
        self.cache = FileCache("data/cache")

    def fetch(self, code: str) -> dict:
        cache_key = f"sector_{code}"
        cached = self.cache.get_pickle("industry", cache_key, ttl_seconds=1800)
        if cached:
            return cached
        errors: list[str] = []
        boards = self._fetch_belong_boards(code, errors)
        industry_flow = self._fetch_ak_flow("industry", errors)
        concept_flow = self._fetch_ak_flow("concept", errors)
        boards = self._merge_flow(boards, industry_flow, concept_flow)
        summary = self._summary(boards)
        payload = {
            "boards": boards,
            "industry_flow": industry_flow,
            "concept_flow": concept_flow,
            "summary": summary,
            "errors": errors,
        }
        self.cache.set_pickle("industry", cache_key, payload)
        return payload

    def _fetch_belong_boards(self, code: str, errors: list[str]) -> pd.DataFrame:
        frames = []
        ak_profile = self._fetch_ak_profile_board(code, errors)
        if not ak_profile.empty:
            frames.append(ak_profile)
        if ef is None:
            errors.append({"source": "efinance", "interface": "get_belong_board", "error_type": "ImportError", "message": "efinance 未安装", "fallback_used": "sina_or_ths_board"})
        else:
            df, err = safe_fetch("efinance", "get_belong_board", lambda: ef.stock.get_belong_board(code), retries=2, min_interval=0.8, cache=self.cache)
            errors.extend(err)
            try:
                normalized = _normalize_belong_board(df)
                if not normalized.empty:
                    frames.append(normalized)
            except Exception as exc:
                errors.append({"source": "efinance", "interface": "get_belong_board", "error_type": exc.__class__.__name__, "message": str(exc), "fallback_used": "sina_or_ths_board"})

        for source, fetcher in (("sina", self._fetch_sina_boards), ("ths", self._fetch_ths_boards)):
            try:
                frame = fetcher(code, errors)
                if not frame.empty:
                    frames.append(frame)
                    break
            except Exception as exc:
                errors.append({"source": source, "interface": "belong_board_fallback", "error_type": exc.__class__.__name__, "message": str(exc), "fallback_used": "next_board_source"})

        if not frames:
            return pd.DataFrame()
        boards = pd.concat(frames, ignore_index=True, sort=False)
        if "board_name" not in boards.columns:
            return pd.DataFrame()
        boards = boards.dropna(subset=["board_name"])
        return boards.drop_duplicates("board_name", keep="first").reset_index(drop=True)

    def _fetch_ak_profile_board(self, code: str, errors: list[str]) -> pd.DataFrame:
        if ak is None:
            errors.append({"source": "akshare", "interface": "stock_individual_info_em", "error_type": "ImportError", "message": "AkShare 未安装", "fallback_used": "efinance_board"})
            return pd.DataFrame()
        df, err = safe_fetch("akshare", "stock_individual_info_em", lambda: ak.stock_individual_info_em(symbol=code), retries=1, min_interval=1.2, cache=self.cache)
        errors.extend(err)
        if df is None or df.empty:
            return pd.DataFrame()
        try:
            data = dict(zip(df.iloc[:, 0].astype(str), df.iloc[:, 1]))
        except Exception:
            return pd.DataFrame()
        industry = data.get("行业") or data.get("所属行业")
        if not industry:
            return pd.DataFrame()
        return _board_frame([str(industry)], "akshare_profile", stock_code=code, board_type="industry")

    def _request_text(self, url: str, encoding: str | None = None) -> str:
        response = requests.get(
            url,
            timeout=float(self.config.get("data", {}).get("timeout", 12)),
            headers={
                "User-Agent": "Mozilla/5.0 (stock-picker-ui)",
                "Referer": "https://finance.sina.com.cn/",
            },
            verify=False,
            proxies={"http": None, "https": None, "all": None},
        )
        response.raise_for_status()
        if encoding:
            response.encoding = encoding
        return response.text

    def _fetch_sina_boards(self, code: str, errors: list[str]) -> pd.DataFrame:
        url = f"https://vip.stock.finance.sina.com.cn/corp/go.php/vCI_CorpOtherInfo/stockid/{code}/menu_num/5.phtml"
        text, err = safe_fetch("sina", "vCI_CorpOtherInfo", lambda: self._request_text(url, "gbk"), retries=1, min_interval=0.8, cache=self.cache)
        errors.extend(err)
        if not text:
            return pd.DataFrame()
        try:
            tables = pd.read_html(StringIO(text))
        except Exception as exc:
            errors.append({"source": "sina", "interface": "read_html_board_tables", "error_type": exc.__class__.__name__, "message": str(exc), "fallback_used": "ths_board"})
            return pd.DataFrame()

        frames = []
        for table in tables:
            if table.empty:
                continue
            first_col = table.iloc[:, 0].dropna().astype(str).str.strip()
            text_blob = " ".join(first_col.tolist())
            if "所属行业板块" in text_blob:
                names = [name for name in first_col.tolist() if name not in {"所属行业板块", "同行业个股"} and not name.startswith("备注")]
                frames.append(_board_frame(names[:3], "sina", stock_code=code, board_type="industry"))
            elif "所属概念板块" in text_blob:
                names = [name for name in first_col.tolist() if name not in {"所属概念板块", "概念板块", "同概念个股"}]
                frames.append(_board_frame(names[:30], "sina", stock_code=code, board_type="concept"))
        return pd.concat([f for f in frames if not f.empty], ignore_index=True, sort=False) if frames else pd.DataFrame()

    def _fetch_ths_boards(self, code: str, errors: list[str]) -> pd.DataFrame:
        url = f"https://stockpage.10jqka.com.cn/{code}/"
        text, err = safe_fetch("ths", "stockpage_company_details", lambda: self._request_text(url, "utf-8"), retries=1, min_interval=0.8, cache=self.cache)
        errors.extend(err)
        if not text:
            return pd.DataFrame()
        names = []
        concept_match = re.search(r"<dt>\s*涉及概念[:：]\s*</dt>\s*<dd[^>]*title=[\"']([^\"']+)[\"']", text, re.S)
        if concept_match:
            concepts = html.unescape(concept_match.group(1))
            names.extend([item.strip() for item in re.split(r"[，,、/]", concepts) if item.strip()])
        return _board_frame(names[:30], "ths", stock_code=code, board_type="concept")

    def _fetch_ak_flow(self, kind: str, errors: list[str]) -> pd.DataFrame:
        if ak is None:
            errors.append({"source": "akshare", "interface": f"{kind}_fund_flow", "error_type": "ImportError", "message": "AkShare 未安装", "fallback_used": "efinance_board"})
            return pd.DataFrame()
        try:
            if kind == "industry":
                df, err = safe_fetch("akshare", "stock_fund_flow_industry", lambda: ak.stock_fund_flow_industry(symbol="即时"), retries=1, min_interval=1.5, cache=self.cache)
                errors.extend(err)
                return _normalize_flow(df, "akshare_industry_flow")
            df, err = safe_fetch("akshare", "stock_fund_flow_concept", lambda: ak.stock_fund_flow_concept(symbol="即时"), retries=1, min_interval=1.5, cache=self.cache)
            errors.extend(err)
            return _normalize_flow(df, "akshare_concept_flow")
        except Exception as exc:
            errors.append({"source": "akshare", "interface": f"{kind}_fund_flow", "error_type": exc.__class__.__name__, "message": str(exc), "fallback_used": "efinance_board"})
            return pd.DataFrame()

    def _merge_flow(self, boards: pd.DataFrame, industry_flow: pd.DataFrame, concept_flow: pd.DataFrame) -> pd.DataFrame:
        if boards is None or boards.empty:
            return pd.DataFrame()
        view = boards.copy()
        flow = pd.concat([industry_flow, concept_flow], ignore_index=True)
        if flow.empty or "board_name" not in flow.columns:
            view["flow_pct"] = None
            view["net_flow"] = None
            view["leader"] = None
            return view
        flow = flow.drop_duplicates("board_name")
        merged = view.merge(flow[["board_name", "flow_pct", "net_flow", "leader"]] if {"flow_pct", "net_flow", "leader"}.issubset(flow.columns) else flow, on="board_name", how="left")
        if "board_pct" not in merged.columns:
            merged["board_pct"] = pd.NA
        merged["board_pct"] = pd.to_numeric(merged["board_pct"], errors="coerce")
        if "flow_pct" in merged.columns:
            merged["board_pct"] = merged["board_pct"].fillna(pd.to_numeric(merged["flow_pct"], errors="coerce"))
        return merged

    def _summary(self, boards: pd.DataFrame) -> dict:
        if boards is None or boards.empty:
            return {
                "available": False,
                "primary_boards": [],
                "top_board": None,
                "top_board_pct": None,
                "avg_top3_pct": None,
                "positive_count": 0,
                "net_flow_sum": None,
                "source": "unavailable",
            }
        view = boards.copy()
        if "board_pct" in view.columns:
            view = view.sort_values("board_pct", ascending=False, na_position="last")
        primary = view.head(6)
        top = primary.iloc[0].to_dict() if not primary.empty else {}
        pct_series = pd.to_numeric(primary.get("board_pct", pd.Series(dtype=float)), errors="coerce").dropna()
        flow_series = pd.to_numeric(view.get("net_flow", pd.Series(dtype=float)), errors="coerce").dropna()
        return {
            "available": True,
            "primary_boards": primary.get("board_name", pd.Series(dtype=str)).dropna().astype(str).tolist(),
            "top_board": top.get("board_name"),
            "top_board_pct": _num(top.get("board_pct")),
            "avg_top3_pct": _num(pct_series.head(3).mean()) if not pct_series.empty else None,
            "positive_count": int((pct_series > 0).sum()) if not pct_series.empty else 0,
            "net_flow_sum": _num(flow_series.sum()) if not flow_series.empty else None,
            "source": self._source_label(view),
        }

    @staticmethod
    def _source_label(view: pd.DataFrame) -> str:
        sources = []
        if "source" in view.columns:
            sources = [str(item) for item in view["source"].dropna().unique().tolist()]
        label = " + ".join(sources) if sources else "board_fallback"
        if "net_flow" in view.columns and view["net_flow"].notna().any():
            label = f"{label} + akshare_flow"
        return label
