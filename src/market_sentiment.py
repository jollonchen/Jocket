from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
import math
from typing import Callable
import requests

import numpy as np
import pandas as pd

from .cache_utils import FileCache, safe_fetch
from .data_fetcher import _disable_process_proxies
from .rotation_analyzer import RotationAnalyzer
from .utils import ensure_dirs

_disable_process_proxies()

try:
    import akshare as ak
except Exception:  # pragma: no cover
    ak = None

try:
    import efinance as ef
except Exception:  # pragma: no cover
    ef = None


def _num(value, default: float | None = None) -> float | None:
    try:
        if value is None or pd.isna(value):
            return default
        num = float(value)
        if math.isinf(num) or math.isnan(num):
            return default
        return num
    except Exception:
        return default


def _clip(value: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, float(value)))


def _date_key(value) -> str:
    return pd.to_datetime(value).strftime("%Y%m%d")


def _display_date(value) -> str:
    return pd.to_datetime(value).strftime("%Y/%m/%d")


def _first_present(row: pd.Series | dict, keys: list[str], default=None):
    for key in keys:
        try:
            value = row.get(key)
        except Exception:
            value = None
        if value is not None and not pd.isna(value):
            return value
    return default


def _normalize_pool(df: pd.DataFrame | None, pool_type: str, date: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    rename = {
        "代码": "code",
        "名称": "name",
        "涨跌幅": "pct",
        "最新价": "price",
        "成交额": "amount",
        "流通市值": "float_market_cap",
        "总市值": "market_cap",
        "换手率": "turnover",
        "封板资金": "seal_fund",
        "封单资金": "seal_fund",
        "首次封板时间": "first_limit_time",
        "最后封板时间": "last_limit_time",
        "炸板次数": "break_count",
        "开板次数": "break_count",
        "涨停统计": "limit_stat",
        "连板数": "limit_streak",
        "所属行业": "industry",
        "入选理由": "reason",
        "是否新高": "new_high",
        "量比": "volume_ratio",
        "涨停价": "limit_price",
        "振幅": "amplitude",
        "连续跌停": "down_streak",
        "动态市盈率": "pe_dynamic",
        "板上成交额": "limit_board_amount",
    }
    view = df.rename(columns=rename).copy()
    keep = [
        "code",
        "name",
        "pct",
        "price",
        "amount",
        "float_market_cap",
        "market_cap",
        "turnover",
        "seal_fund",
        "first_limit_time",
        "last_limit_time",
        "break_count",
        "limit_stat",
        "limit_streak",
        "industry",
        "reason",
        "new_high",
        "volume_ratio",
        "limit_price",
        "amplitude",
        "down_streak",
        "pe_dynamic",
        "limit_board_amount",
    ]
    view = view[[col for col in keep if col in view.columns]]
    for col in [
        "pct",
        "price",
        "amount",
        "float_market_cap",
        "market_cap",
        "turnover",
        "seal_fund",
        "break_count",
        "limit_streak",
        "volume_ratio",
        "limit_price",
        "amplitude",
        "down_streak",
        "pe_dynamic",
        "limit_board_amount",
    ]:
        if col in view.columns:
            view[col] = pd.to_numeric(view[col], errors="coerce")
    for col in ["code", "name", "industry", "reason", "limit_stat", "first_limit_time", "last_limit_time"]:
        if col in view.columns:
            view[col] = view[col].astype(str).replace({"nan": ""})
    view["pool_type"] = pool_type
    view["date"] = pd.to_datetime(date)
    return view


@dataclass
class PoolBundle:
    limit_up: pd.DataFrame
    broken: pd.DataFrame
    limit_down: pd.DataFrame
    strong: pd.DataFrame
    warnings: list[dict]


class MarketSentimentAnalyzer:
    """Build a market emotion dashboard from public A-share sources.

    The original reference screen uses proprietary labels. This module keeps the
    same dimensions while deriving them from public涨停/炸板/跌停, market breadth,
    and board-rotation data. Missing fields remain explicit instead of invented.
    """

    CACHE_VERSION = "v5"

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        ensure_dirs()
        self.cache = FileCache("data/cache")
        self.ttl = int(self.config.get("data", {}).get("sentiment_ttl_seconds", 900))

    def analyze(self, trade_date, window_days: int = 60, force_refresh: bool = False, backfill_history: bool = True) -> dict:
        trade_ts = pd.to_datetime(trade_date).normalize()
        window_days = int(max(14, min(120, window_days)))
        min_history_days = int(self.config.get("market", {}).get("min_history_days", 60) or 60)
        required_history_days = int(max(window_days, min_history_days))
        cache_key = f"market_sentiment_{self.CACHE_VERSION}_{_date_key(trade_ts)}_{window_days}_{required_history_days}_{int(bool(backfill_history))}"
        if not force_refresh:
            cached = self.cache.get_pickle("industry", cache_key, ttl_seconds=self.ttl)
            if cached:
                return cached

        warnings: list[dict] = []
        latest = self._fetch_day(trade_ts, warnings, force_refresh=force_refresh)
        dates = pd.bdate_range(end=trade_ts, periods=required_history_days)
        history_rows = []
        remote_backfill_days = required_history_days if backfill_history else int(self.config.get("data", {}).get("sentiment_remote_backfill_days", 0))
        for offset, day in enumerate(dates):
            is_recent = offset >= len(dates) - remote_backfill_days
            day_key = f"sentiment_day_{self.CACHE_VERSION}_{_date_key(day)}"
            cached_day = self.cache.get_pickle("industry", day_key, ttl_seconds=24 * 3600 * 14)
            is_very_recent = day.normalize() >= (pd.Timestamp.now() - pd.Timedelta(days=3)).normalize()
            if day.normalize() == trade_ts:
                day_payload = latest
            elif cached_day and not (force_refresh and is_very_recent) and not (backfill_history and self._cached_day_needs_backfill(cached_day)):
                day_payload = cached_day
            elif is_recent:
                day_payload = self._fetch_day(
                    day,
                    warnings,
                    force_refresh=bool((force_refresh and is_very_recent) or (cached_day and backfill_history))
                )
            else:
                warnings.append({"source": "cache", "interface": "sentiment_day_history", "message": f"{day.strftime('%Y-%m-%d')} 暂无缓存，跳过远端补齐以控制页面耗时", "fallback_used": "empty_history_row"})
                day_payload = {"metrics": self._empty_day_metrics(day), "limit_up": pd.DataFrame()}
            history_rows.append(day_payload["metrics"])
        history = pd.DataFrame(history_rows).drop_duplicates("date").sort_values("date")
        history = self._add_derived_scores_to_history(history)

        indices = self._fetch_index_snapshot(warnings)
        breadth = self._fetch_market_breadth(warnings, indices)
        boards = self._build_board_ladder(latest, warnings)
        metrics = self._derive_scores(latest["metrics"], history, breadth, boards)

        # Update the last row of history with fully derived metrics for the current day
        if not history.empty:
            last_idx = history.index[-1]
            for col, val in metrics.items():
                if col in history.columns:
                    history.loc[last_idx, col] = val

        metrics["explanations"] = self._build_metric_explanations(metrics, latest["metrics"], breadth)
        heatmap = self._build_heatmap(history, latest, boards)
        month_stats = self._build_month_stats(history)
        tactics = self._build_tactics(metrics, boards, latest, history)
        watchlist = self._build_watchlist(latest, boards, metrics)
        board_members = self._build_board_members(latest)

        payload = {
            "available": True,
            "trade_date": trade_ts.strftime("%Y-%m-%d"),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "涨跌停池 + 市场宽度/指数兜底",
            "metrics": metrics,
            "latest": latest,
            "history": history.tail(window_days).copy(),
            "calculation_history": history,
            "required_history_days": required_history_days,
            "heatmap": heatmap,
            "month_stats": month_stats,
            "boards": boards,
            "board_members": board_members,
            "indices": indices,
            "breadth": breadth,
            "tactics": tactics,
            "watchlist": watchlist,
            "warnings": warnings,
        }
        self.cache.set_pickle("industry", cache_key, payload)
        return payload

    @staticmethod
    def _cached_day_needs_backfill(day_payload: dict | None) -> bool:
        if not isinstance(day_payload, dict):
            return True
        metrics = day_payload.get("metrics", {}) or {}
        if _num(metrics.get("history_missing"), 0):
            return True
        pool_keys = ("limit_up", "broken", "limit_down", "strong")
        pool_sizes = []
        for key in pool_keys:
            frame = day_payload.get(key)
            pool_sizes.append(len(frame) if isinstance(frame, pd.DataFrame) else 0)
        core_counts = [
            _num(metrics.get("limit_up_count"), 0) or 0,
            _num(metrics.get("broken_count"), 0) or 0,
            _num(metrics.get("limit_down_count"), 0) or 0,
            _num(metrics.get("strong_count"), 0) or 0,
        ]
        return sum(pool_sizes) == 0 and sum(core_counts) == 0

    def _fetch_day(self, day: pd.Timestamp, warnings: list[dict], force_refresh: bool = False) -> dict:
        key = f"sentiment_day_{self.CACHE_VERSION}_{_date_key(day)}"
        if not force_refresh:
            is_recent = day.normalize() >= (pd.Timestamp.now() - pd.Timedelta(days=3)).normalize()
            ttl = self.ttl if is_recent else 24 * 3600 * 14
            cached = self.cache.get_pickle("industry", key, ttl_seconds=ttl)
            if cached:
                return cached

        bundle = self._fetch_pools(day, warnings)
        metrics = self._day_metrics(day, bundle)
        payload = {
            "date": day.strftime("%Y-%m-%d"),
            "metrics": metrics,
            "limit_up": bundle.limit_up,
            "broken": bundle.broken,
            "limit_down": bundle.limit_down,
            "strong": bundle.strong,
            "warnings": bundle.warnings,
        }
        self.cache.set_pickle("industry", key, payload)
        return payload

    def _call_pool(self, name: str, func: Callable, day: pd.Timestamp, warnings: list[dict]) -> pd.DataFrame:
        if ak is None:
            warnings.append({"source": "akshare", "interface": name, "message": "AkShare 未安装"})
            return pd.DataFrame()
        df, errors = safe_fetch(
            "akshare",
            name,
            lambda: func(date=_date_key(day)),
            retries=0,
            min_interval=0.8,
            cache=self.cache,
        )
        warnings.extend(errors)
        return df if isinstance(df, pd.DataFrame) else pd.DataFrame()

    def _fetch_pools(self, day: pd.Timestamp, warnings: list[dict]) -> PoolBundle:
        if ak is None:
            return PoolBundle(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), warnings)
        jobs = {
            "limit_up": ("stock_zt_pool_em", ak.stock_zt_pool_em, "涨停"),
            "broken": ("stock_zt_pool_zbgc_em", ak.stock_zt_pool_zbgc_em, "炸板"),
            "limit_down": ("stock_zt_pool_dtgc_em", ak.stock_zt_pool_dtgc_em, "跌停"),
            "strong": ("stock_zt_pool_strong_em", ak.stock_zt_pool_strong_em, "强势"),
        }
        results = {key: pd.DataFrame() for key in jobs}
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_map = {
                executor.submit(self._call_pool, interface, func, day, warnings): (key, label)
                for key, (interface, func, label) in jobs.items()
            }
            for future in as_completed(future_map):
                key, label = future_map[future]
                try:
                    results[key] = _normalize_pool(future.result(), label, day)
                except Exception as exc:
                    warnings.append({"source": "akshare", "interface": jobs[key][0], "message": str(exc), "fallback_used": "empty_pool"})
        return PoolBundle(results["limit_up"], results["broken"], results["limit_down"], results["strong"], warnings)

    def _day_metrics(self, day: pd.Timestamp, bundle: PoolBundle) -> dict:
        limit_count = len(bundle.limit_up)
        broken_count = len(bundle.broken)
        down_count = len(bundle.limit_down)
        strong_count = len(bundle.strong)
        history_missing = int((limit_count + broken_count + down_count + strong_count) == 0)
        total_attempts = limit_count + broken_count
        broken_rate = broken_count / total_attempts if total_attempts else None
        max_streak = _num(bundle.limit_up.get("limit_streak", pd.Series(dtype=float)).max(), 0) or 0
        if not max_streak and "limit_stat" in bundle.limit_up.columns:
            parsed = bundle.limit_up["limit_stat"].astype(str).str.extract(r"/(\d+)")[0]
            max_streak = _num(pd.to_numeric(parsed, errors="coerce").max(), 0) or 0
        high_streak_count = int(pd.to_numeric(bundle.limit_up.get("limit_streak", pd.Series(dtype=float)), errors="coerce").ge(3).sum())
        first_limit_count = int(pd.to_numeric(bundle.limit_up.get("limit_streak", pd.Series(dtype=float)), errors="coerce").fillna(1).le(1).sum())
        industries = bundle.limit_up.get("industry", pd.Series(dtype=str)).replace("", np.nan).dropna()
        top_industry = industries.value_counts().index[0] if not industries.empty else None
        hot_industry_count = int((industries.value_counts() >= 3).sum()) if not industries.empty else 0
        seal_fund = _num(pd.to_numeric(bundle.limit_up.get("seal_fund", pd.Series(dtype=float)), errors="coerce").sum(), 0) or 0
        amount = _num(pd.to_numeric(bundle.limit_up.get("amount", pd.Series(dtype=float)), errors="coerce").sum(), 0) or 0
        return {
            "date": pd.to_datetime(day),
            "limit_up_count": int(limit_count),
            "broken_count": int(broken_count),
            "limit_down_count": int(down_count),
            "strong_count": int(strong_count),
            "broken_rate": broken_rate,
            "max_streak": int(max_streak),
            "high_streak_count": int(high_streak_count),
            "first_limit_count": int(first_limit_count),
            "hot_industry_count": int(hot_industry_count),
            "top_industry": top_industry,
            "seal_fund": seal_fund,
            "limit_amount": amount,
            "history_missing": history_missing,
        }

    @staticmethod
    def _empty_day_metrics(day: pd.Timestamp) -> dict:
        return {
            "date": pd.to_datetime(day),
            "limit_up_count": 0,
            "broken_count": 0,
            "limit_down_count": 0,
            "strong_count": 0,
            "broken_rate": None,
            "max_streak": 0,
            "high_streak_count": 0,
            "first_limit_count": 0,
            "hot_industry_count": 0,
            "top_industry": None,
            "seal_fund": 0,
            "limit_amount": 0,
            "history_missing": 1,
        }

    @staticmethod
    def _market_breadth_from_frame(frame: pd.DataFrame | None, source: str) -> dict:
        if frame is None or frame.empty:
            return {"available": False, "source": source, "up": None, "down": None, "flat": None, "up_ratio": None, "amount": None}
        rename = {
            "涨跌幅": "pct",
            "涨跌额": "change",
            "成交额": "amount",
            "最新涨跌幅": "pct",
            "change_pct": "pct",
            "pct_chg": "pct",
            "f3": "pct",
            "f6": "amount",
        }
        view = frame.rename(columns=rename)
        pct = pd.to_numeric(view.get("pct", pd.Series(dtype=str)).astype(str).str.replace("%", "", regex=False), errors="coerce")
        amount = pd.to_numeric(view.get("amount", pd.Series(dtype=str)).astype(str).str.replace(",", "", regex=False), errors="coerce")
        up = int((pct > 0).sum())
        down = int((pct < 0).sum())
        flat = int((pct == 0).sum())
        total = up + down + flat
        return {
            "available": total > 0,
            "source": source,
            "up": up if total else None,
            "down": down if total else None,
            "flat": flat if total else None,
            "up_ratio": up / total if total else None,
            "amount": _num(amount.sum(), None) if total else None,
        }

    @staticmethod
    def _proxy_breadth_from_indices(indices: pd.DataFrame | None) -> dict:
        if indices is None or indices.empty:
            return {"available": False, "source": "指数代理", "up": None, "down": None, "flat": None, "up_ratio": None, "amount": None}
        pct = pd.to_numeric(indices.get("pct", pd.Series(dtype=float)), errors="coerce").dropna()
        if pct.empty:
            return {"available": False, "source": "指数代理", "up": None, "down": None, "flat": None, "up_ratio": None, "amount": None}
        up = int((pct > 0).sum())
        down = int((pct < 0).sum())
        flat = int((pct == 0).sum())
        total = up + down + flat
        amount = pd.to_numeric(indices.get("amount", pd.Series(dtype=float)), errors="coerce")
        return {
            "available": total > 0,
            "source": "指数代理",
            "up": up,
            "down": down,
            "flat": flat,
            "up_ratio": up / total if total else None,
            "amount": _num(amount.sum(), None),
            "proxy": True,
        }

    def _fetch_market_breadth(self, warnings: list[dict], indices: pd.DataFrame | None = None) -> dict:
        frame = pd.DataFrame()
        source = "unavailable"
        if ef is not None and bool(self.config.get("data", {}).get("sentiment_use_efinance_breadth", False)):
            try:
                frame = ef.stock.get_realtime_quotes()
                source = "efinance.get_realtime_quotes"
            except Exception as exc:
                warnings.append({"source": "efinance", "interface": "get_realtime_quotes", "message": str(exc), "fallback_used": "akshare_spot"})
        if (frame is None or frame.empty) and ak is not None:
            frame, errors = safe_fetch("akshare", "stock_zh_a_spot_em", ak.stock_zh_a_spot_em, retries=0, min_interval=1.0, cache=self.cache)
            warnings.extend(errors)
            source = "akshare.stock_zh_a_spot_em" if isinstance(frame, pd.DataFrame) and not frame.empty else source
        parsed = self._market_breadth_from_frame(frame, source)
        if parsed.get("available"):
            return parsed

        if frame is not None and not frame.empty:
            warnings.append({"source": source, "interface": "market_breadth_parse", "message": "行情表缺少可识别涨跌幅字段", "fallback_used": "eastmoney_qt_clist"})

        proxy = self._proxy_breadth_from_indices(indices)
        if proxy.get("available"):
            warnings.append({"source": "index_snapshot", "interface": "market_breadth_proxy", "message": "全市场宽度源不可用，使用指数代理", "fallback_used": "index_proxy"})
            return proxy

        if not parsed.get("available"):
            em = self._fetch_eastmoney_market_breadth(warnings)
            if em.get("available"):
                return em
        return parsed

    def _fetch_index_snapshot(self, warnings: list[dict]) -> pd.DataFrame:
        rows = []
        if ak is not None:
            df, errors = safe_fetch("akshare", "stock_zh_index_spot_em", ak.stock_zh_index_spot_em, retries=0, min_interval=1.0, cache=self.cache)
            warnings.extend(errors)
            if isinstance(df, pd.DataFrame) and not df.empty:
                rename = {
                    "代码": "code",
                    "名称": "name",
                    "最新价": "price",
                    "涨跌幅": "pct",
                    "成交额": "amount",
                }
                view = df.rename(columns=rename)
                codes = {"000001", "399001", "399006", "000688", "000016", "000300", "899050"}
                rows = view[view.get("code", pd.Series(dtype=str)).astype(str).isin(codes)].to_dict("records")
        if not rows:
            rows = self._fetch_eastmoney_indices(warnings)
        if not rows:
            rows = [
                {"code": "000001", "name": "上证指数", "price": None, "pct": None, "amount": None},
                {"code": "399001", "name": "深证成指", "price": None, "pct": None, "amount": None},
                {"code": "399006", "name": "创业板指", "price": None, "pct": None, "amount": None},
                {"code": "000688", "name": "科创50", "price": None, "pct": None, "amount": None},
                {"code": "000016", "name": "上证50", "price": None, "pct": None, "amount": None},
                {"code": "000300", "name": "沪深300", "price": None, "pct": None, "amount": None},
                {"code": "899050", "name": "北证50", "price": None, "pct": None, "amount": None},
            ]
        out = pd.DataFrame(rows)
        for col in ["price", "pct", "amount"]:
            if col in out.columns:
                out[col] = pd.to_numeric(out[col], errors="coerce")
        return out

    def _request_eastmoney_json(self, url: str, params: dict, warnings: list[dict], interface: str) -> dict | None:
        urls = [url]
        if "push2.eastmoney.com" in url:
            urls.append(url.replace("push2.eastmoney.com", "push2delay.eastmoney.com"))
        last_error = None
        for target in urls:
            for _ in range(2):
                try:
                    response = requests.get(
                        target,
                        params=params,
                        timeout=float(self.config.get("data", {}).get("timeout", 12)),
                        headers={"User-Agent": "Mozilla/5.0 (Jocket)", "Referer": "https://quote.eastmoney.com/"},
                        verify=False,
                        proxies={"http": None, "https": None, "all": None},
                    )
                    response.raise_for_status()
                    return response.json()
                except Exception as exc:
                    last_error = exc
        warnings.append({"source": "eastmoney", "interface": interface, "message": str(last_error), "fallback_used": "degraded"})
        return None

    def _fetch_eastmoney_market_breadth(self, warnings: list[dict]) -> dict:
        rows = []
        total = None
        page_size = 100
        for page in range(1, 80):
            payload = self._request_eastmoney_json(
                "https://push2.eastmoney.com/api/qt/clist/get",
                {
                    "pn": page,
                    "pz": page_size,
                    "po": 1,
                    "np": 1,
                    "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                    "fltt": 2,
                    "invt": 2,
                    "fid": "f3",
                    "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
                    "fields": "f3,f6",
                },
                warnings,
                "qt_clist_a_breadth",
            )
            data = (payload or {}).get("data") or {}
            chunk = data.get("diff") or []
            if total is None:
                total = _num(data.get("total"), None)
            if not chunk:
                if total and len(rows) < int(total):
                    warnings.append({"source": "eastmoney", "interface": "qt_clist_a_breadth", "message": f"分页数据不完整：{len(rows)}/{int(total)}", "fallback_used": "index_proxy"})
                    return {"available": False, "source": "eastmoney.qt_clist", "up": None, "down": None, "flat": None, "up_ratio": None, "amount": None}
                break
            rows.extend(chunk)
            if total and len(rows) >= int(total):
                break
            if len(chunk) < page_size:
                break
        if not rows:
            return {"available": False, "source": "eastmoney.qt_clist", "up": None, "down": None, "flat": None, "up_ratio": None, "amount": None}
        frame = pd.DataFrame(rows)
        pct = pd.to_numeric(frame.get("f3", pd.Series(dtype=float)), errors="coerce")
        amount = pd.to_numeric(frame.get("f6", pd.Series(dtype=float)), errors="coerce")
        up = int((pct > 0).sum())
        down = int((pct < 0).sum())
        flat = int((pct == 0).sum())
        total = up + down + flat
        return {
            "available": total > 0,
            "source": "eastmoney.qt_clist",
            "up": up,
            "down": down,
            "flat": flat,
            "up_ratio": up / total if total else None,
            "amount": _num(amount.sum(), None),
        }

    def _fetch_eastmoney_indices(self, warnings: list[dict]) -> list[dict]:
        code_map = {
            "1.000001": ("000001", "上证指数"),
            "0.399001": ("399001", "深证成指"),
            "0.399006": ("399006", "创业板指"),
            "1.000688": ("000688", "科创50"),
            "1.000016": ("000016", "上证50"),
            "1.000300": ("000300", "沪深300"),
            "0.899050": ("899050", "北证50"),
        }
        payload = self._request_eastmoney_json(
            "https://push2.eastmoney.com/api/qt/ulist.np/get",
            {
                "fltt": 2,
                "invt": 2,
                "fields": "f12,f14,f2,f3,f6",
                "secids": ",".join(code_map.keys()),
            },
            warnings,
            "qt_ulist_indices",
        )
        rows = ((payload or {}).get("data") or {}).get("diff") or []
        out = []
        for row in rows:
            secid = next((key for key, item in code_map.items() if item[0] == str(row.get("f12"))), None)
            code, fallback_name = code_map.get(secid, (str(row.get("f12") or ""), str(row.get("f14") or "")))
            out.append(
                {
                    "code": code,
                    "name": row.get("f14") or fallback_name,
                    "price": row.get("f2"),
                    "pct": row.get("f3"),
                    "amount": row.get("f6"),
                }
            )
        return out

    def _build_board_ladder(self, latest: dict, warnings: list[dict]) -> pd.DataFrame:
        pool = latest.get("limit_up", pd.DataFrame())
        broken = latest.get("broken", pd.DataFrame())
        down = latest.get("limit_down", pd.DataFrame())
        strong = latest.get("strong", pd.DataFrame())
        frames = []
        if pool is not None and not pool.empty and "industry" in pool.columns:
            up_group = pool.groupby("industry", dropna=True).agg(
                limit_count=("code", "count"),
                max_streak=("limit_streak", "max"),
                seal_fund=("seal_fund", "sum"),
                amount=("amount", "sum"),
            )
            frames.append(up_group)
        if broken is not None and not broken.empty and "industry" in broken.columns:
            b_group = broken.groupby("industry", dropna=True).agg(broken_count=("code", "count"))
            frames.append(b_group)
        if down is not None and not down.empty and "industry" in down.columns:
            d_group = down.groupby("industry", dropna=True).agg(down_count=("code", "count"))
            frames.append(d_group)
        if strong is not None and not strong.empty and "industry" in strong.columns:
            s_group = strong.groupby("industry", dropna=True).agg(strong_count=("code", "count"))
            frames.append(s_group)
        if not frames:
            return pd.DataFrame()
        board = pd.concat(frames, axis=1).fillna(0).reset_index().rename(columns={"industry": "board_name"})
        board = board[board["board_name"].astype(str).str.strip() != ""]
        for col in ["limit_count", "broken_count", "down_count", "strong_count", "max_streak", "seal_fund", "amount"]:
            if col not in board.columns:
                board[col] = 0
            board[col] = pd.to_numeric(board[col], errors="coerce").fillna(0)
        total_attempts = board.get("limit_count", 0) + board.get("broken_count", 0)
        board["broken_rate"] = np.where(total_attempts > 0, board.get("broken_count", 0) / total_attempts, 0)
        breadth_bonus = np.where(board["limit_count"] >= 2, board["max_streak"].clip(upper=5) * 360, board["max_streak"].clip(upper=5) * 120)
        board["strength"] = (
            board.get("limit_count", 0) * 1200
            + board.get("strong_count", 0).clip(upper=20) * 85
            + breadth_bonus
            + np.log1p(board.get("seal_fund", 0).clip(lower=0)) * 70
            - board.get("broken_count", 0) * 220
            - board.get("down_count", 0) * 360
        ).round(1)
        board["role"] = board.apply(self._board_role, axis=1)
        board["risk_note"] = board.apply(self._board_risk, axis=1)
        board["strategy"] = board.apply(self._board_strategy, axis=1)
        board["evidence"] = board.apply(
            lambda row: (
                f"涨停{int(row.get('limit_count', 0))}家、强势{int(row.get('strong_count', 0))}家、"
                f"炸板{int(row.get('broken_count', 0))}家、最高{int(row.get('max_streak', 0))}板"
            ),
            axis=1,
        )

        if bool(self.config.get("data", {}).get("sentiment_use_rotation_enrich", False)):
            try:
                rotation = RotationAnalyzer(self.config).analyze(top_n=30, force_refresh=False).get("combined", pd.DataFrame())
                if rotation is not None and not rotation.empty:
                    enrich = rotation.rename(columns={"board_name": "board_name", "board_pct": "board_pct", "net_flow": "net_flow"})
                    cols = [c for c in ["board_name", "board_pct", "net_flow", "leader", "leader_pct"] if c in enrich.columns]
                    board = board.merge(enrich[cols].drop_duplicates("board_name"), on="board_name", how="left")
            except Exception as exc:
                warnings.append({"source": "rotation", "interface": "RotationAnalyzer.analyze", "message": str(exc), "fallback_used": "limit_pool_industry_group"})

        role_rank = {"主线": 0, "支线": 1, "高标孤立": 2, "轮动": 3}
        board["_role_rank"] = board["role"].map(role_rank).fillna(4)
        return board.sort_values(["_role_rank", "strength"], ascending=[True, False]).drop(columns=["_role_rank"]).reset_index(drop=True)

    @staticmethod
    def _board_role(row: pd.Series) -> str:
        limit_count = _num(row.get("limit_count"), 0) or 0
        strong_count = _num(row.get("strong_count"), 0) or 0
        max_streak = _num(row.get("max_streak"), 0) or 0
        if limit_count == 1 and max_streak >= 4:
            return "高标孤立"
        if limit_count >= 4 or (limit_count >= 2 and strong_count >= 6):
            return "主线"
        if limit_count >= 2 or strong_count >= 8:
            return "支线"
        return "轮动"

    @staticmethod
    def _board_risk(row: pd.Series) -> str:
        if _num(row.get("broken_rate"), 0) >= 0.35:
            return "炸板率偏高，关注日内分歧和回封效率。"
        if _num(row.get("down_count"), 0) >= 2:
            return "板块内亏钱效应抬升，避免无量追高。"
        if _num(row.get("limit_count"), 0) >= 5:
            return "一致性较强，次日注意分化。"
        return "结合龙头承接和板块扩散确认。"

    @staticmethod
    def _board_strategy(row: pd.Series) -> str:
        role = row.get("role")
        if role == "主线":
            return "主线前排优先，后排只在分歧转一致时跟踪。"
        if role == "支线":
            return "支线以观察补涨为主，优先看是否出现连续扩散。"
        if role == "高标孤立":
            return "单票高度不等于板块主线，只记录高标反馈。"
        return "轮动方向只做低吸观察，不做追涨假设。"

    def _derive_scores(self, latest: dict, history: pd.DataFrame, breadth: dict, boards: pd.DataFrame) -> dict:
        limit_count = _num(latest.get("limit_up_count"), 0) or 0
        broken_count = _num(latest.get("broken_count"), 0) or 0
        down_count = _num(latest.get("limit_down_count"), 0) or 0
        strong_count = _num(latest.get("strong_count"), 0) or 0
        broken_rate = _num(latest.get("broken_rate"), 0) or 0
        max_streak = _num(latest.get("max_streak"), 0) or 0
        hot_boards = _num(latest.get("hot_industry_count"), 0) or 0
        up_ratio = _num(breadth.get("up_ratio"), None) if breadth else None
        breadth_score = 50 if up_ratio is None else 35 + up_ratio * 35

        raw_score = (
            min(30, limit_count / 3)
            + min(20, max_streak * 4)
            + min(15, strong_count / 22)
            + min(10, hot_boards * 2)
            + breadth_score * 0.18
            - min(18, broken_rate * 58)
            - min(16, down_count * 1.7)
        )
        emotion = round(_clip(raw_score), 1)
        short_emotion = round(_clip(emotion + max_streak * 1.2 - broken_rate * 12), 1)
        big_market = round(_clip(breadth_score), 1)
        loss_effect = round(_clip(down_count * 6.5 + broken_rate * 62 + (1 - (up_ratio if up_ratio is not None else 0.5)) * 18 - limit_count * 0.06), 1)
        divergence = round(_clip(abs(short_emotion - big_market) * 0.45 + broken_rate * 38 + down_count * 1.2), 1)
        temperature = round(_clip(emotion * 0.75 + min(25, limit_count / 5) + min(10, max_streak * 1.4) - down_count * 0.8), 1)
        period = self._period_label(emotion, broken_rate, down_count, max_streak)
        suggestion = self._suggestion(period, divergence, broken_rate, down_count)
        prev = history.iloc[-2].to_dict() if len(history) >= 2 else {}
        prev_premium = self._prev_limit_premium(latest, prev)
        return {
            "emotion_score": emotion,
            "short_emotion": short_emotion,
            "big_market_factor": big_market,
            "loss_effect": loss_effect,
            "divergence": divergence,
            "temperature": temperature,
            "period": period,
            "suggestion": suggestion,
            "limit_up_count": int(limit_count),
            "broken_count": int(broken_count),
            "limit_down_count": int(down_count),
            "strong_count": int(strong_count),
            "broken_rate": broken_rate,
            "max_streak": int(max_streak),
            "prev_limit_premium": prev_premium,
            "hot_board_count": int(hot_boards),
            "up_count": breadth.get("up") if breadth else None,
            "down_count": breadth.get("down") if breadth else None,
            "market_amount": breadth.get("amount") if breadth else None,
            "data_quality": self._data_quality(breadth, boards, history),
            "top_board": boards.iloc[0]["board_name"] if boards is not None and not boards.empty else latest.get("top_industry"),
        }

    def _add_derived_scores_to_history(self, history: pd.DataFrame) -> pd.DataFrame:
        if history is None or history.empty:
            return history

        emotion_scores = []
        short_emotions = []
        big_market_factors = []
        loss_effects = []
        divergences = []
        temperatures = []

        for idx, row in history.iterrows():
            limit_count = _num(row.get("limit_up_count"), 0) or 0
            broken_count = _num(row.get("broken_count"), 0) or 0
            down_count = _num(row.get("limit_down_count"), 0) or 0
            strong_count = _num(row.get("strong_count"), 0) or 0
            broken_rate = _num(row.get("broken_rate"), 0) or 0
            max_streak = _num(row.get("max_streak"), 0) or 0
            hot_boards = _num(row.get("hot_industry_count"), 0) or 0

            # Historical rows don't have historical breadth, so we use neutral breadth_score = 50, up_ratio = None
            breadth_score = 50
            up_ratio = None

            raw_score = (
                min(30, limit_count / 3)
                + min(20, max_streak * 4)
                + min(15, strong_count / 22)
                + min(10, hot_boards * 2)
                + breadth_score * 0.18
                - min(18, broken_rate * 58)
                - min(16, down_count * 1.7)
            )
            emotion = round(_clip(raw_score), 1)
            short_emotion = round(_clip(emotion + max_streak * 1.2 - broken_rate * 12), 1)
            big_market = round(_clip(breadth_score), 1)
            loss_effect = round(_clip(down_count * 6.5 + broken_rate * 62 + (1 - (up_ratio if up_ratio is not None else 0.5)) * 18 - limit_count * 0.06), 1)
            divergence = round(_clip(abs(short_emotion - big_market) * 0.45 + broken_rate * 38 + down_count * 1.2), 1)
            temperature = round(_clip(emotion * 0.75 + min(25, limit_count / 5) + min(10, max_streak * 1.4) - down_count * 0.8), 1)

            emotion_scores.append(emotion)
            short_emotions.append(short_emotion)
            big_market_factors.append(big_market)
            loss_effects.append(loss_effect)
            divergences.append(divergence)
            temperatures.append(temperature)

        history = history.copy()
        history["emotion_score"] = emotion_scores
        history["short_emotion"] = short_emotions
        history["big_market_factor"] = big_market_factors
        history["loss_effect"] = loss_effects
        history["divergence"] = divergences
        history["temperature"] = temperatures
        return history


    @staticmethod
    def _period_label(score: float, broken_rate: float, down_count: float, max_streak: float) -> str:
        if score >= 72 and max_streak >= 4 and broken_rate <= 0.22:
            return "高潮"
        if score >= 62:
            return "发酵"
        if score >= 52:
            return "启动"
        if score >= 38:
            return "常态"
        if down_count >= 10 or broken_rate >= 0.35:
            return "冰点"
        return "退潮"

    @staticmethod
    def _suggestion(period: str, divergence: float, broken_rate: float, down_count: float) -> str:
        if period in {"高潮", "发酵"} and divergence < 25:
            return "主线前排可继续观察，后排避免追高。"
        if period == "高潮":
            return "情绪高位但分歧抬升，重点看龙头承接和回封质量。"
        if period == "启动":
            return "可观察主线扩散，仓位以确认型为主。"
        if period == "冰点":
            return "先看修复而非抢反弹，等待亏钱效应收敛。"
        if broken_rate >= 0.28 or down_count >= 8:
            return "风险偏高，降低追涨，关注强弱切换。"
        return "情绪中性，等待方向进一步确认。"

    @staticmethod
    def _prev_limit_premium(latest: dict, prev: dict) -> float | None:
        prev_count = _num(prev.get("limit_up_count"), None)
        today_strong = _num(latest.get("strong_count"), None)
        if prev_count is None or not prev_count:
            return None
        return round(_clip((today_strong or 0) / prev_count * 12 - 3, -20, 30), 1)

    @staticmethod
    def _data_quality(breadth: dict, boards: pd.DataFrame, history: pd.DataFrame) -> str:
        issues = []
        if not breadth or not breadth.get("available"):
            issues.append("市场宽度缺失")
        if boards is None or boards.empty:
            issues.append("板块资金缺失")
        if history is None or len(history) < 14:
            issues.append("历史窗口不足")
        elif pd.to_numeric(history.get("history_missing", pd.Series(dtype=float)), errors="coerce").fillna(0).sum() > 0:
            issues.append("部分历史待缓存")
        return "OK" if not issues else " / ".join(issues)

    @staticmethod
    def _build_metric_explanations(metrics: dict, latest: dict, breadth: dict) -> list[dict]:
        up_ratio = breadth.get("up_ratio") if breadth else None
        broken_rate = _num(latest.get("broken_rate"), 0) or 0
        return [
            {
                "指标": "情绪综合指数",
                "当前值": metrics.get("emotion_score"),
                "公式/口径": "涨停强度 + 连板高度 + 强势股扩散 + 热点板块数 + 市场宽度 - 炸板惩罚 - 跌停惩罚",
                "核心输入": f"涨停{latest.get('limit_up_count')}、强势{latest.get('strong_count')}、最高{latest.get('max_streak')}板、炸板率{broken_rate:.1%}、跌停{latest.get('limit_down_count')}",
                "数据状态": metrics.get("data_quality"),
            },
            {
                "指标": "炸板率",
                "当前值": metrics.get("broken_rate"),
                "公式/口径": "炸板数 / (涨停数 + 炸板数)",
                "核心输入": f"炸板{latest.get('broken_count')}、涨停{latest.get('limit_up_count')}",
                "数据状态": "涨停池/炸板池",
            },
            {
                "指标": "三维分歧度",
                "当前值": metrics.get("divergence"),
                "公式/口径": "|超短情绪 - 大盘系数| * 0.45 + 炸板率 * 38 + 跌停数 * 1.2",
                "核心输入": f"超短{metrics.get('short_emotion')}、大盘{metrics.get('big_market_factor')}、炸板率{broken_rate:.1%}",
                "数据状态": "市场宽度缺失时大盘系数用中性50",
            },
            {
                "指标": "亏钱效应",
                "当前值": metrics.get("loss_effect"),
                "公式/口径": "跌停数、炸板率、下跌扩散共同加权；涨停家数抵消一部分压力",
                "核心输入": f"跌停{latest.get('limit_down_count')}、炸板率{broken_rate:.1%}、上涨占比{up_ratio:.1%}" if up_ratio is not None else f"跌停{latest.get('limit_down_count')}、炸板率{broken_rate:.1%}、市场宽度缺失",
                "数据状态": "市场宽度缺失时使用中性宽度",
            },
            {
                "指标": "昨日涨停溢价",
                "当前值": metrics.get("prev_limit_premium"),
                "公式/口径": "用今日强势股数量 / 昨日涨停数量估算涨停承接，不等同于逐股真实溢价",
                "核心输入": f"今日强势{latest.get('strong_count')}、昨日涨停来自历史缓存",
                "数据状态": "代理估算；历史缺失时显示为空",
            },
        ]

    @staticmethod
    def _build_board_members(latest: dict) -> pd.DataFrame:
        frames = []
        for key, label in [("limit_up", "涨停"), ("broken", "炸板"), ("limit_down", "跌停"), ("strong", "强势")]:
            frame = latest.get(key, pd.DataFrame())
            if frame is None or frame.empty:
                continue
            view = frame.copy()
            view["member_type"] = label
            frames.append(view)
        if not frames:
            return pd.DataFrame()
        members = pd.concat(frames, ignore_index=True, sort=False)
        if "industry" not in members.columns:
            members["industry"] = ""
        return members

    def _build_heatmap(self, history: pd.DataFrame, latest: dict, boards: pd.DataFrame | None = None) -> pd.DataFrame:
        rows = []
        day_pools = latest.get("limit_up", pd.DataFrame())
        if day_pools is None or day_pools.empty:
            return pd.DataFrame()
        if boards is not None and not boards.empty and "board_name" in boards.columns:
            top_industries = boards.head(12)["board_name"].dropna().astype(str).tolist()
        else:
            top_industries = day_pools.get("industry", pd.Series(dtype=str)).replace("", np.nan).dropna().value_counts().head(12).index.tolist()
        for _, row in history.iterrows():
            date = pd.to_datetime(row["date"])
            day_payload = latest if date.strftime("%Y-%m-%d") == latest.get("date") else self.cache.get_pickle("industry", f"sentiment_day_{self.CACHE_VERSION}_{_date_key(date)}", ttl_seconds=24 * 3600 * 14)
            pool = (day_payload or {}).get("limit_up", pd.DataFrame())
            if pool is None or pool.empty or "industry" not in pool.columns:
                continue
            grouped = pool.groupby("industry").agg(
                limit_count=("code", "count"),
                max_streak=("limit_streak", "max"),
                seal_fund=("seal_fund", "sum"),
            )
            for industry in top_industries:
                if industry not in grouped.index:
                    rows.append({"date": date, "board_name": industry, "heat": 0, "raw_heat": 0, "limit_count": 0, "max_streak": 0, "seal_fund": 0, "state": "冷"})
                    continue
                item = grouped.loc[industry]
                raw_heat = float(item.get("limit_count", 0)) * 1200 + float(item.get("max_streak", 0)) * 260 + math.log1p(float(item.get("seal_fund", 0) or 0)) * 55
                rows.append(
                    {
                        "date": date,
                        "board_name": industry,
                        "raw_heat": round(raw_heat, 1),
                        "limit_count": int(item.get("limit_count", 0) or 0),
                        "max_streak": int(item.get("max_streak", 0) or 0),
                        "seal_fund": float(item.get("seal_fund", 0) or 0),
                    }
                )
        heatmap = pd.DataFrame(rows)
        if heatmap.empty:
            return heatmap
        nonzero = pd.to_numeric(heatmap["raw_heat"], errors="coerce").fillna(0)
        positive = nonzero[nonzero > 0]
        if positive.empty:
            heatmap["heat"] = 0
        else:
            lo = positive.quantile(0.1)
            hi = positive.quantile(0.9)
            if hi <= lo:
                hi = positive.max()
                lo = positive.min()
            if hi <= lo:
                heatmap["heat"] = np.where(nonzero > 0, 50, 0)
            else:
                heatmap["heat"] = ((nonzero - lo) / (hi - lo) * 100).clip(0, 100).round(1)
        heatmap["state"] = np.where(heatmap["heat"] >= 70, "热", np.where(heatmap["heat"] >= 35, "温", "冷"))
        return heatmap

    @staticmethod
    def _build_month_stats(history: pd.DataFrame) -> pd.DataFrame:
        if history is None or history.empty:
            return pd.DataFrame()
        view = history.copy()
        view["month"] = pd.to_datetime(view["date"]).dt.strftime("%Y/%m")
        broken_rate = pd.to_numeric(view.get("broken_rate", pd.Series(dtype=float)), errors="coerce").fillna(0)
        ice = (pd.to_numeric(view.get("limit_up_count", pd.Series(dtype=float)), errors="coerce").fillna(0) <= 35) | (
            pd.to_numeric(view.get("limit_down_count", pd.Series(dtype=float)), errors="coerce").fillna(0) >= 8
        ) | (broken_rate >= 0.32)
        view["ice_point"] = ice.astype(int)
        return view.groupby("month", as_index=False).agg(ice_points=("ice_point", "sum"))

    def _build_tactics(self, metrics: dict, boards: pd.DataFrame, latest: dict, history: pd.DataFrame) -> dict:
        period = metrics.get("period")
        divergence = _num(metrics.get("divergence"), 0) or 0
        broken_rate = _num(metrics.get("broken_rate"), 0) or 0
        top_board = metrics.get("top_board") or "暂无主线"
        if period in {"高潮", "发酵"} and divergence < 30:
            aggressive, stable = "3-5成", "2-4成"
        elif period == "启动":
            aggressive, stable = "2-4成", "1-3成"
        else:
            aggressive, stable = "1-2成", "0-1成"
        risk = "空间板高位一致风险"
        if broken_rate >= 0.28:
            risk = "空间板高位一致风险，叠加炸板率偏高"
        if metrics.get("limit_down_count", 0) >= 8:
            risk = "亏钱效应扩散，需防止一致转分歧"
        chance = "接力窗口修复" if period in {"启动", "发酵"} else "等待冰点修复"
        return {
            "main_line": top_board,
            "aggressive_position": aggressive,
            "stable_position": stable,
            "mismatch": ["主线核心", "龙头换手板"] if period in {"启动", "发酵", "高潮"} else ["低位修复", "回避无量跟风"],
            "timeline": [
                {"time": "09:25", "action": f"观察 {top_board} 竞价强度是否一致。"},
                {"time": "09:35", "action": "观察炸板率是否低于 18%。"},
                {"time": "10:00", "action": "若主线继续加强，聚焦前排核心。"},
            ],
            "risk": {"title": risk, "level": "中" if divergence < 35 else "高", "detail": f"三维分歧度 {divergence:.1f}，炸板率 {broken_rate:.1%}。"},
            "chance": {"title": chance, "grade": "B" if period in {"启动", "发酵"} else "C", "detail": "触发条件：情绪指数回稳、前排换手后回封、板块扩散重新抬升。"},
            "battlefield": [
                {"name": "高位打板", "score": 66.7 if period in {"高潮", "发酵"} else 45.0, "tag": "观察", "note": "高位一致后更易分歧，优先回避缩量加速。"},
                {"name": "低位首板", "score": 66.7 if period in {"启动", "常态"} else 55.0, "tag": "主攻", "note": "优先选择分时回封质量高、板块共振的首板。"},
                {"name": "龙头反抽", "score": 75.0 if period in {"冰点", "退潮"} else 58.0, "tag": "观察", "note": "仅在冰点修复或主线分歧小时试错。"},
                {"name": "空仓观望", "score": 84.0 if divergence >= 35 else 52.0, "tag": "观察", "note": "若竞价与开盘反馈不达标，优先执行防守策略。"},
            ],
        }

    @staticmethod
    def _build_watchlist(latest: dict, boards: pd.DataFrame, metrics: dict) -> pd.DataFrame:
        strong = latest.get("strong", pd.DataFrame())
        limit_up = latest.get("limit_up", pd.DataFrame())
        candidates = pd.concat([limit_up.head(20), strong.head(50)], ignore_index=True, sort=False)
        if candidates.empty:
            return pd.DataFrame()
        board_roles = {}
        if boards is not None and not boards.empty:
            board_roles = dict(zip(boards["board_name"].astype(str), boards["role"].astype(str)))
        candidates = candidates.drop_duplicates("code").copy()
        for col in ["limit_streak", "turnover", "volume_ratio", "pct"]:
            if col not in candidates.columns:
                candidates[col] = 0
        candidates["priority_score"] = (
            pd.to_numeric(candidates.get("limit_streak", 0), errors="coerce").fillna(0) * 18
            + pd.to_numeric(candidates.get("turnover", 0), errors="coerce").fillna(0).clip(0, 30)
            + pd.to_numeric(candidates.get("volume_ratio", 0), errors="coerce").fillna(0).clip(0, 5) * 5
            + pd.to_numeric(candidates.get("pct", 0), errors="coerce").fillna(0).clip(0, 20)
        )
        candidates["role"] = candidates.get("industry", pd.Series(dtype=str)).astype(str).map(board_roles).fillna("观察")
        candidates["buy_condition"] = np.where(
            pd.to_numeric(candidates.get("limit_streak", 0), errors="coerce").fillna(0) >= 2,
            "分歧后回封且成交放量",
            "首板放量回封",
        )
        candidates["risk_note"] = np.where(
            candidates["role"].eq("主线"),
            "不能炸板放量回落",
            "观察板块共振",
        )
        out = candidates.sort_values("priority_score", ascending=False).head(8).copy()
        out["priority"] = ["A类" if i < 2 else "B类" if i < 5 else "C类" for i in range(len(out))]
        return out
