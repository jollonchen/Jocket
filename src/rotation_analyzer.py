from __future__ import annotations

from datetime import datetime

import pandas as pd

from .cache_utils import FileCache, safe_fetch
from .data_fetcher import _disable_process_proxies
from .sector_fetcher import _normalize_ak_board_market, _normalize_flow
from .utils import ensure_dirs

_disable_process_proxies()

try:
    import akshare as ak
except Exception:  # pragma: no cover
    ak = None


FLOW_WINDOWS = {
    "即时": "now",
    "3日排行": "d3",
    "5日排行": "d5",
    "10日排行": "d10",
    "20日排行": "d20",
}


class RotationAnalyzer:
    """Daily industry/concept rotation analyzer powered by AkShare endpoints."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        ensure_dirs()
        self.cache = FileCache("data/cache")

    def analyze(self, top_n: int = 30, force_refresh: bool = False) -> dict:
        ttl = int(self.config.get("data", {}).get("rotation_ttl_seconds", 900))
        cache_key = f"akshare_rotation_{top_n}"
        if not force_refresh:
            cached = self.cache.get_pickle("industry", cache_key, ttl_seconds=ttl)
            if cached:
                return cached

        errors: list[dict] = []
        industry_flow = self._fetch_flow_group("industry", errors)
        concept_flow = self._fetch_flow_group("concept", errors)
        industry_market = self._fetch_board_market("industry", errors)
        concept_market = self._fetch_board_market("concept", errors)

        industry = self._build_rotation_frame(industry_flow, industry_market, "行业")
        concept = self._build_rotation_frame(concept_flow, concept_market, "热点/概念")
        combined = pd.concat([industry, concept], ignore_index=True, sort=False)
        if not combined.empty:
            combined = combined.sort_values("rotation_score", ascending=False).reset_index(drop=True)

        payload = {
            "available": not combined.empty,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "AkShare: stock_fund_flow_industry / stock_fund_flow_concept / stock_board_*_name_em",
            "summary": self._summary(combined, industry, concept),
            "combined": combined.head(int(top_n) * 2),
            "industry": industry.head(int(top_n)),
            "concept": concept.head(int(top_n)),
            "errors": errors,
        }
        self.cache.set_pickle("industry", cache_key, payload)
        return payload

    def _fetch_flow_group(self, kind: str, errors: list[dict]) -> dict[str, pd.DataFrame]:
        out: dict[str, pd.DataFrame] = {}
        if ak is None:
            errors.append({"source": "akshare", "interface": f"{kind}_fund_flow", "error_type": "ImportError", "message": "AkShare 未安装"})
            return out
        func = ak.stock_fund_flow_industry if kind == "industry" else ak.stock_fund_flow_concept
        for symbol, suffix in FLOW_WINDOWS.items():
            df, err = safe_fetch("akshare", f"stock_fund_flow_{kind}_{symbol}", lambda s=symbol: func(symbol=s), retries=1, min_interval=1.0, cache=self.cache)
            errors.extend(err)
            out[suffix] = _normalize_flow(df, f"akshare_{kind}_flow_{suffix}") if df is not None else pd.DataFrame()
        return out

    def _fetch_board_market(self, kind: str, errors: list[dict]) -> pd.DataFrame:
        if ak is None:
            return pd.DataFrame()
        func = ak.stock_board_industry_name_em if kind == "industry" else ak.stock_board_concept_name_em
        df, err = safe_fetch("akshare", f"stock_board_{kind}_name_em", func, retries=1, min_interval=1.2, cache=self.cache)
        errors.extend(err)
        return _normalize_ak_board_market(df, f"akshare_{kind}_market") if df is not None else pd.DataFrame()

    def _build_rotation_frame(self, flows: dict[str, pd.DataFrame], market: pd.DataFrame, board_type: str) -> pd.DataFrame:
        base = flows.get("now", pd.DataFrame()).copy()
        if base.empty and market is not None and not market.empty:
            base = market.copy()
        if base.empty or "board_name" not in base.columns:
            return pd.DataFrame()

        base = base.drop_duplicates("board_name").copy()
        if market is not None and not market.empty and "board_name" in market.columns:
            enrich_cols = [c for c in ["board_name", "board_code", "board_pct", "amount", "turnover_rate", "up_count", "down_count", "leader", "leader_pct"] if c in market.columns]
            base = base.merge(market[enrich_cols].drop_duplicates("board_name"), on="board_name", how="left", suffixes=("", "_market"))

        for suffix in ["d3", "d5", "d10", "d20"]:
            frame = flows.get(suffix, pd.DataFrame())
            if frame is None or frame.empty or "board_name" not in frame.columns:
                continue
            cols = [c for c in ["board_name", "flow_pct", "net_flow"] if c in frame.columns]
            base = base.merge(
                frame[cols].drop_duplicates("board_name").rename(columns={"flow_pct": f"flow_pct_{suffix}", "net_flow": f"net_flow_{suffix}"}),
                on="board_name",
                how="left",
            )

        if "board_pct" not in base.columns:
            base["board_pct"] = pd.NA
        if "flow_pct" in base.columns:
            base["board_pct"] = pd.to_numeric(base["board_pct"], errors="coerce").fillna(pd.to_numeric(base["flow_pct"], errors="coerce"))

        for col in ["flow_pct", "net_flow", "leader_pct", "board_pct", "flow_pct_d3", "flow_pct_d5", "flow_pct_d10", "flow_pct_d20", "net_flow_d3", "net_flow_d5"]:
            if col in base.columns:
                base[col] = pd.to_numeric(base[col], errors="coerce")

        base["board_type"] = board_type
        base["momentum_score"] = self._scale(base.get("board_pct"), 40)
        base["flow_score"] = self._scale(base.get("net_flow"), 35)
        base["persistence_score"] = self._persistence_score(base)
        base["leader_score"] = self._scale(base.get("leader_pct"), 10)
        base["rotation_score"] = (
            base["momentum_score"].fillna(0)
            + base["flow_score"].fillna(0)
            + base["persistence_score"].fillna(0)
            + base["leader_score"].fillna(0)
        ).round(1)
        base["opportunity"] = base.apply(self._opportunity_label, axis=1)
        base["risk_note"] = base.apply(self._risk_note, axis=1)
        return base.sort_values("rotation_score", ascending=False).reset_index(drop=True)

    @staticmethod
    def _scale(series: pd.Series | None, weight: float) -> pd.Series:
        if series is None:
            return pd.Series(dtype=float)
        nums = pd.to_numeric(series, errors="coerce")
        valid = nums.dropna()
        if valid.empty:
            return pd.Series([0.0] * len(nums), index=nums.index)
        lo, hi = valid.quantile(0.1), valid.quantile(0.9)
        if hi == lo:
            return pd.Series([weight / 2] * len(nums), index=nums.index)
        return ((nums - lo) / (hi - lo) * weight).clip(0, weight)

    @staticmethod
    def _persistence_score(df: pd.DataFrame) -> pd.Series:
        cols = [col for col in ["flow_pct_d3", "flow_pct_d5", "flow_pct_d10", "flow_pct_d20"] if col in df.columns]
        if not cols:
            return pd.Series([0.0] * len(df), index=df.index)
        values = df[cols].apply(pd.to_numeric, errors="coerce")
        positive_count = (values > 0).sum(axis=1)
        avg_rank = values.rank(pct=True).mean(axis=1).fillna(0)
        return (positive_count / max(len(cols), 1) * 8 + avg_rank * 7).clip(0, 15)

    @staticmethod
    def _opportunity_label(row: pd.Series) -> str:
        score = float(row.get("rotation_score") or 0)
        pct = float(row.get("board_pct") or 0)
        net = float(row.get("net_flow") or 0)
        if score >= 75 and pct > 0 and net > 0:
            return "强轮动: 资金和涨幅共振"
        if score >= 60 and net > 0:
            return "资金回流: 等待价格确认"
        if pct > 0 and net <= 0:
            return "涨幅领先但资金分歧"
        if net > 0:
            return "低位吸筹观察"
        return "仅跟踪"

    @staticmethod
    def _risk_note(row: pd.Series) -> str:
        pct = float(row.get("board_pct") or 0)
        net = float(row.get("net_flow") or 0)
        leader_pct = float(row.get("leader_pct") or 0)
        if pct >= 5 or leader_pct >= 15:
            return "领涨过快，避免追高，优先等分歧承接。"
        if pct > 0 and net < 0:
            return "板块上涨但主力净流出，注意冲高回落。"
        if pct < 0 and net > 0:
            return "资金逆势流入，适合观察修复，不宜提前定论。"
        return "结合指数环境、龙头持续性和成交额验证。"

    @staticmethod
    def _summary(combined: pd.DataFrame, industry: pd.DataFrame, concept: pd.DataFrame) -> dict:
        if combined.empty:
            return {"available": False}
        top = combined.iloc[0].to_dict()
        positive_flow = pd.to_numeric(combined.get("net_flow", pd.Series(dtype=float)), errors="coerce").gt(0).sum()
        positive_pct = pd.to_numeric(combined.get("board_pct", pd.Series(dtype=float)), errors="coerce").gt(0).sum()
        return {
            "available": True,
            "top_board": top.get("board_name"),
            "top_type": top.get("board_type"),
            "top_score": top.get("rotation_score"),
            "top_net_flow": top.get("net_flow"),
            "top_pct": top.get("board_pct"),
            "positive_flow_count": int(positive_flow),
            "positive_pct_count": int(positive_pct),
            "industry_count": int(len(industry)),
            "concept_count": int(len(concept)),
        }
