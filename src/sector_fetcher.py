from __future__ import annotations

from pathlib import Path

import pandas as pd

from .utils import ensure_dirs

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


class SectorFetcher:
    """Fetch A-share board / concept membership and market heat with safe fallbacks."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        ensure_dirs()
        Path("data/fundamentals").mkdir(parents=True, exist_ok=True)

    def fetch(self, code: str) -> dict:
        errors: list[str] = []
        boards = self._fetch_belong_boards(code, errors)
        industry_flow = self._fetch_ak_flow("industry", errors)
        concept_flow = self._fetch_ak_flow("concept", errors)
        boards = self._merge_flow(boards, industry_flow, concept_flow)
        summary = self._summary(boards)
        return {
            "boards": boards,
            "industry_flow": industry_flow,
            "concept_flow": concept_flow,
            "summary": summary,
            "errors": errors,
        }

    def _fetch_belong_boards(self, code: str, errors: list[str]) -> pd.DataFrame:
        if ef is None:
            errors.append("efinance 未安装，无法获取所属板块")
            return pd.DataFrame()
        try:
            df = ef.stock.get_belong_board(code)
            return _normalize_belong_board(df)
        except Exception as exc:
            errors.append(f"efinance 所属板块获取失败：{exc}")
            return pd.DataFrame()

    def _fetch_ak_flow(self, kind: str, errors: list[str]) -> pd.DataFrame:
        if ak is None:
            errors.append("AkShare 未安装，无法获取板块资金流")
            return pd.DataFrame()
        try:
            if kind == "industry":
                return _normalize_flow(ak.stock_fund_flow_industry(symbol="即时"), "akshare_industry_flow")
            return _normalize_flow(ak.stock_fund_flow_concept(symbol="即时"), "akshare_concept_flow")
        except Exception as exc:
            errors.append(f"AkShare {kind} 板块资金流获取失败：{exc}")
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
            "source": "efinance + akshare" if "net_flow" in view.columns and view["net_flow"].notna().any() else "efinance",
        }
