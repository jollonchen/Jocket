from __future__ import annotations

import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

from .cache_utils import FileCache, safe_fetch
from .providers.a_stock_data_provider import AStockDataProvider
from .utils import display_code, ensure_dirs, normalize_a_share_code
from .sector_fetcher import SectorFetcher

try:
    import akshare as ak
except Exception:  # pragma: no cover
    ak = None


def _safe_value(value: Any):
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _as_float(value: Any):
    try:
        value = _safe_value(value)
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip().replace(",", "").replace("%", "")
            if value in {"", "-", "--", "None", "nan"}:
                return None
        return float(value)
    except Exception:
        return None


def _clean_text(value: Any, limit: int | None = None) -> str:
    text = str(_safe_value(value) or "").strip()
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if limit and len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def _has_cjk(value: Any) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in str(value or ""))


def _row_value(df: pd.DataFrame, names: list[str], column):
    if df is None or df.empty or column not in df.columns:
        return None
    for name in names:
        if name in df.index:
            return _safe_value(df.loc[name, column])
    return None


def _statement_to_records(income: pd.DataFrame, balance: pd.DataFrame, cashflow: pd.DataFrame, limit: int) -> pd.DataFrame:
    columns = []
    for df in [income, balance, cashflow]:
        if df is not None and not df.empty:
            columns.extend(list(df.columns))
    periods = sorted(set(columns), reverse=True)[:limit]
    rows = []
    for period in periods:
        revenue = _row_value(income, ["Total Revenue", "Operating Revenue"], period)
        gross_profit = _row_value(income, ["Gross Profit"], period)
        net_income = _row_value(income, ["Net Income Common Stockholders", "Net Income"], period)
        eps = _row_value(income, ["Diluted EPS", "Basic EPS"], period)
        operating_cash_flow = _row_value(cashflow, ["Operating Cash Flow", "Cash Flowsfromusedin Operating Activities Direct"], period)
        free_cash_flow = _row_value(cashflow, ["Free Cash Flow"], period)
        total_assets = _row_value(balance, ["Total Assets"], period)
        total_liab = _row_value(balance, ["Total Liabilities Net Minority Interest", "Current Liabilities"], period)
        equity = _row_value(balance, ["Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"], period)
        bvps = None
        shares = _row_value(balance, ["Ordinary Shares Number", "Share Issued"], period)
        if equity and shares:
            bvps = equity / shares
        rows.append(
            {
                "period": pd.to_datetime(period).strftime("%Y-%m-%d"),
                "totalRevenue": revenue,
                "grossProfit": gross_profit,
                "netIncome": net_income,
                "deductedNetIncome": None,
                "operatingCashFlow": operating_cash_flow,
                "freeCashFlow": free_cash_flow,
                "totalAssets": total_assets,
                "totalLiab": total_liab,
                "totalStockholderEquity": equity,
                "grossMargin": gross_profit / revenue if revenue else None,
                "netMargin": net_income / revenue if revenue else None,
                "roe": net_income / equity if net_income and equity else None,
                "roa": net_income / total_assets if net_income and total_assets else None,
                "debtToEquity": total_liab / equity if total_liab and equity else None,
                "eps": eps,
                "bvps": bvps,
                "dividend": None,
                "dividendYield": None,
            }
        )
    return pd.DataFrame(rows)


class FundamentalFetcher:
    def __init__(self, config: dict | None = None):
        self.config = config or {}
        ensure_dirs()
        Path("data/fundamentals").mkdir(parents=True, exist_ok=True)
        self.cache = FileCache("data/cache")

    def fetch(self, code: str, latest_price: float | None = None) -> dict:
        yahoo_code = normalize_a_share_code(code)
        ticker = display_code(yahoo_code)
        cache_key = f"fundamental_{ticker}_{datetime.now().strftime('%Y%m%d')}"
        cached = self.cache.get_pickle("fundamentals", cache_key, ttl_seconds=86400)
        if cached:
            cached.setdefault("profile", {})["latest_price"] = latest_price or cached.get("profile", {}).get("latest_price")
            cached.setdefault("profile", {})["data_source"] = str(cached.get("profile", {}).get("data_source", "")) + " + cache"
            return cached
            
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_y = executor.submit(self._fetch_yfinance, yahoo_code, latest_price)
            future_ak = executor.submit(self._fetch_akshare, ticker)
            future_a = executor.submit(self._fetch_a_stock_data, ticker)
            future_cn = executor.submit(self._fetch_chinese_profile, ticker)
            future_sec = executor.submit(SectorFetcher(self.config).fetch, ticker)
            
            y = future_y.result()
            ak_payload = future_ak.result()
            a_stock_payload = future_a.result()
            cn_profile = future_cn.result()
            sector_payload = future_sec.result()
            
        payload = self._merge_payload(ticker, yahoo_code, y, ak_payload, cn_profile, sector_payload, latest_price, a_stock_payload)
        self.cache.set_pickle("fundamentals", cache_key, payload)
        return payload

    def _fetch_yfinance(self, yahoo_code: str, latest_price: float | None) -> dict:
        errors = []
        info = {}
        annual = pd.DataFrame()
        quarterly = pd.DataFrame()
        try:
            ticker = yf.Ticker(yahoo_code)
            try:
                info, info_errors = safe_fetch("yfinance", "ticker.info", lambda: ticker.info or {}, retries=2, min_interval=0.8, cache=self.cache)
                info = info or {}
                errors.extend(info_errors)
            except Exception as exc:
                errors.append(f"yfinance info失败：{exc}")
            try:
                income, e1 = safe_fetch("yfinance", "income_stmt", lambda: ticker.income_stmt, retries=1, min_interval=0.8, cache=self.cache)
                balance, e2 = safe_fetch("yfinance", "balance_sheet", lambda: ticker.balance_sheet, retries=1, min_interval=0.8, cache=self.cache)
                cashflow, e3 = safe_fetch("yfinance", "cashflow", lambda: ticker.cashflow, retries=1, min_interval=0.8, cache=self.cache)
                errors.extend(e1 + e2 + e3)
                annual = _statement_to_records(income, balance, cashflow, 5)
            except Exception as exc:
                errors.append(f"yfinance 年度财务失败：{exc}")
            try:
                q_income, e1 = safe_fetch("yfinance", "quarterly_income_stmt", lambda: ticker.quarterly_income_stmt, retries=1, min_interval=0.8, cache=self.cache)
                q_balance, e2 = safe_fetch("yfinance", "quarterly_balance_sheet", lambda: ticker.quarterly_balance_sheet, retries=1, min_interval=0.8, cache=self.cache)
                q_cashflow, e3 = safe_fetch("yfinance", "quarterly_cashflow", lambda: ticker.quarterly_cashflow, retries=1, min_interval=0.8, cache=self.cache)
                errors.extend(e1 + e2 + e3)
                quarterly = _statement_to_records(q_income, q_balance, q_cashflow, 12)
            except Exception as exc:
                errors.append(f"yfinance 季度财务失败：{exc}")
        except Exception as exc:
            errors.append(f"yfinance整体失败：{exc}")
        return {"info": info, "annual": annual, "quarterly": quarterly, "errors": errors}

    def _fetch_akshare(self, ticker: str) -> dict:
        out = {"info": {}, "errors": []}
        if ak is None:
            out["errors"].append({"source": "akshare", "interface": "stock_individual_info_em", "error_type": "ImportError", "message": "AkShare未安装", "fallback_used": "yfinance"})
            return out
        df, errors = safe_fetch("akshare", "stock_individual_info_em", lambda: ak.stock_individual_info_em(symbol=ticker), retries=1, min_interval=1.5, cache=self.cache)
        out["errors"].extend(errors)
        try:
            if df is not None and not df.empty and {"item", "value"}.issubset(df.columns):
                out["info"] = dict(zip(df["item"], df["value"]))
        except Exception as exc:
            out["errors"].append({"source": "akshare", "interface": "stock_individual_info_em", "error_type": exc.__class__.__name__, "message": str(exc), "fallback_used": "yfinance"})
        return out

    def _fetch_a_stock_data(self, ticker: str) -> dict:
        provider = AStockDataProvider(self.cache, self.config)
        out = {"quote": {}, "stock_info": {}, "reports": [], "eps_forecast": pd.DataFrame(), "errors": [], "sources": []}
        tasks = {
            "quote": lambda: provider.tencent_quote([ticker]),
            "stock_info": lambda: provider.eastmoney_stock_info(ticker),
            "reports": lambda: provider.eastmoney_reports(ticker, max_pages=2),
            "eps_forecast": lambda: provider.ths_eps_forecast(ticker),
        }
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(func): key for key, func in tasks.items()}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    result = future.result()
                    out[key] = result.data
                    out["errors"].extend(result.warnings or [])
                    if result.data is not None and not (hasattr(result.data, "empty") and result.data.empty):
                        out["sources"].append(f"a-stock-data:{key}")
                except Exception as exc:
                    out["errors"].append({"source": "a-stock-data", "interface": key, "error_type": exc.__class__.__name__, "message": str(exc)})
        return out

    def _fetch_chinese_profile(self, ticker: str) -> dict:
        out = {"info": {}, "errors": [], "sources": []}
        if ak is None:
            out["errors"].append({"source": "akshare", "interface": "chinese_profile", "error_type": "ImportError", "message": "AkShare未安装", "fallback_used": "yfinance"})
            return out

        tasks = {
            "zyjs": lambda: safe_fetch("akshare", "stock_zyjs_ths", lambda: ak.stock_zyjs_ths(symbol=ticker), retries=1, min_interval=1.2, cache=self.cache),
            "cninfo": lambda: safe_fetch("akshare", "stock_profile_cninfo", lambda: ak.stock_profile_cninfo(symbol=ticker), retries=1, min_interval=1.2, cache=self.cache),
        }
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {executor.submit(func): key for key, func in tasks.items()}
            results = {}
            for future in as_completed(futures):
                results[futures[future]] = future.result()

        zyjs, e_zyjs = results["zyjs"]
        cninfo, e_cninfo = results["cninfo"]

        out["errors"].extend(e_zyjs + e_cninfo)
        
        zyjs_info = self._parse_zyjs(zyjs)
        if zyjs_info:
            out["info"].update(zyjs_info)
            out["sources"].append("同花顺主营介绍")

        cninfo_info = self._parse_cninfo_profile(cninfo)
        if cninfo_info:
            for key, value in cninfo_info.items():
                out["info"].setdefault(key, value)
            out["sources"].append("巨潮公司概况")

        if not _has_cjk(out["info"].get("business")):
            fallback = self._fetch_sina_or_ths_business(ticker)
            if fallback.get("business"):
                out["info"]["business"] = fallback["business"]
                out["sources"].append(fallback.get("source", "中文网页"))
            out["errors"].extend(fallback.get("errors", []))
        return out

    def _apply_chinese_profile(self, profile: dict, cn_profile: dict) -> None:
        cn_info = cn_profile.get("info", {}) or {}
        if cn_info.get("name") and not _has_cjk(profile.get("name")):
            profile["name"] = cn_info["name"]
        if cn_info.get("industry"):
            profile["industry"] = cn_info["industry"]
            profile["industry_cn"] = cn_info["industry"]
        if cn_info.get("business"):
            profile["business"] = cn_info["business"]
        if cn_info.get("list_date"):
            profile["list_date"] = cn_info["list_date"]
        if cn_profile.get("sources"):
            profile["business_source"] = " + ".join(cn_profile.get("sources", []))
            current = [item for item in str(profile.get("data_source", "")).split(" + ") if item]
            profile["data_source"] = " + ".join(dict.fromkeys([*current, *cn_profile.get("sources", [])]))

    def _parse_zyjs(self, df: pd.DataFrame | None) -> dict:
        if df is None or df.empty:
            return {}
        info = {}
        text_fields = []
        for _, row in df.iterrows():
            joined = " ".join(_clean_text(v) for v in row.tolist() if _clean_text(v))
            if not joined:
                continue
            if any(key in joined for key in ("主营", "业务", "产品", "经营范围")):
                text_fields.append(joined)
        if text_fields:
            info["business"] = _clean_text("；".join(dict.fromkeys(text_fields)), 1200)
        return info

    def _parse_cninfo_profile(self, df: pd.DataFrame | None) -> dict:
        if df is None or df.empty:
            return {}
        info = {}
        for _, row in df.iterrows():
            values = [_clean_text(v) for v in row.tolist()]
            for idx, value in enumerate(values):
                next_value = values[idx + 1] if idx + 1 < len(values) else ""
                if value in {"公司名称", "证券简称", "股票简称"} and next_value:
                    info.setdefault("name", next_value)
                elif value in {"所属行业", "行业"} and next_value:
                    info.setdefault("industry", next_value)
                elif value in {"主营业务", "经营范围", "公司简介"} and next_value:
                    info.setdefault("business", next_value)
                elif value in {"上市日期", "上市时间"} and next_value:
                    info.setdefault("list_date", next_value)
        columns = {str(col): col for col in df.columns}
        for key, aliases in {
            "name": ["公司名称", "证券简称", "股票简称"],
            "industry": ["所属行业", "行业"],
            "business": ["主营业务", "经营范围", "公司简介"],
            "list_date": ["上市日期", "上市时间"],
        }.items():
            for alias in aliases:
                if alias in columns:
                    series = df[columns[alias]].dropna()
                    if not series.empty:
                        info.setdefault(key, _clean_text(series.iloc[0], 1200 if key == "business" else None))
        return {key: value for key, value in info.items() if value}

    def _fetch_sina_or_ths_business(self, ticker: str) -> dict:
        errors = []
        for source, url, encoding in [
            ("新浪公司资料", f"https://vip.stock.finance.sina.com.cn/corp/go.php/vCI_CorpInfo/stockid/{ticker}.phtml", "gb18030"),
            ("同花顺经营分析", f"https://basic.10jqka.com.cn/{ticker}/operate.html", "gbk"),
        ]:
            text, err = safe_fetch(source, "company_business_page", lambda url=url, encoding=encoding: self._request_text(url, encoding), retries=1, min_interval=1.0, cache=self.cache)
            errors.extend(err)
            business = self._extract_business_from_html(text or "")
            if _has_cjk(business):
                return {"business": business, "source": source, "errors": errors}
        return {"errors": errors}

    def _request_text(self, url: str, encoding: str) -> str:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 stock-picker-ui", "Referer": "https://finance.sina.com.cn/"})
        with urllib.request.urlopen(req, timeout=float(self.config.get("data", {}).get("timeout", 12))) as resp:
            raw = resp.read()
        for enc in (encoding, "utf-8", "gb18030", "gbk"):
            try:
                return raw.decode(enc)
            except Exception:
                pass
        return raw.decode("utf-8", errors="ignore")

    def _extract_business_from_html(self, text: str) -> str:
        if not text:
            return ""
        plain = _clean_text(text)
        for pattern in (
            r"(?:主营业务|经营范围|公司简介)[:：]\s*(.{40,900}?)(?:公司名称|所属行业|发行|上市|办公地址|$)",
            r"(?:主营构成|产品名称|业务名称)[:：]?\s*(.{40,700}?)(?:按行业|按产品|$)",
        ):
            match = re.search(pattern, plain)
            if match:
                return _clean_text(match.group(1), 900)
        return ""

    def _market_name(self, ticker: str, yahoo_code: str) -> tuple[str, str]:
        if yahoo_code.endswith(".SS"):
            if ticker.startswith("688"):
                return "上交所", "科创板"
            return "上交所", "沪市"
        if yahoo_code.endswith(".SZ"):
            if ticker.startswith("300"):
                return "深交所", "创业板"
            return "深交所", "深市"
        if yahoo_code.endswith(".HK"):
            return "港交所", "港股主板"
        # US markets
        if yahoo_code.isupper() and yahoo_code.isalpha():
            return "美股", "纽交所/纳斯达克"
        return "其它", "海外/全球市场"

    def _merge_payload(self, ticker: str, yahoo_code: str, y: dict, ak_payload: dict, cn_profile: dict, sector_payload: dict, latest_price: float | None, a_stock_payload: dict | None = None) -> dict:
        info = y.get("info", {}) or {}
        ak_info = ak_payload.get("info", {}) or {}
        cn_info = cn_profile.get("info", {}) or {}
        a_stock_payload = a_stock_payload or {}
        quote_map = a_stock_payload.get("quote") or {}
        a_quote = quote_map.get(ticker) if isinstance(quote_map, dict) else {}
        if not a_quote and isinstance(quote_map, dict) and quote_map:
            a_quote = next(iter(quote_map.values()), {})
        a_info = a_stock_payload.get("stock_info") or {}
        sector_summary = sector_payload.get("summary", {}) or {}
        primary_boards = sector_summary.get("primary_boards", []) or []
        sector_source = sector_summary.get("source") or "sector_fallback"
        data_sources = ["yfinance"]
        data_sources.extend(a_stock_payload.get("sources", []))
        if ak_info:
            data_sources.append("akshare")
        data_sources.extend(cn_profile.get("sources", []))
        if primary_boards:
            data_sources.append(str(sector_source))
        exchange, market = self._market_name(ticker, yahoo_code)
        market_cap = info.get("marketCap") or ((_as_float(a_quote.get("market_cap_yi")) or 0) * 100000000 if a_quote.get("market_cap_yi") else None)
        shares = info.get("sharesOutstanding")
        float_shares = info.get("floatShares")
        price = latest_price or a_quote.get("price") or info.get("currentPrice") or info.get("regularMarketPrice")
        profile = {
            "code": ticker,
            "yahoo_code": yahoo_code,
            "name": a_quote.get("name") or ak_info.get("股票简称") or cn_info.get("name") or info.get("shortName") or info.get("longName") or ticker,
            "exchange": exchange,
            "market": market,
            "industry": ak_info.get("所属行业") or cn_info.get("industry") or a_info.get("f127") or info.get("industry") or "暂未获取",
            "sector": info.get("sector") or "暂未获取",
            "industry_cn": ak_info.get("所属行业") or cn_info.get("industry") or a_info.get("f127") or (primary_boards[0] if primary_boards else "暂未获取"),
            "belong_boards": primary_boards or ([ak_info.get("所属行业")] if ak_info.get("所属行业") else []),
            "business": cn_info.get("business") or ak_info.get("主营业务") or info.get("longBusinessSummary") or "当前数据源暂不支持",
            "business_source": " + ".join(cn_profile.get("sources", [])) or ("yfinance" if info.get("longBusinessSummary") else ""),
            "list_date": ak_info.get("上市时间") or ak_info.get("上市日期") or cn_info.get("list_date") or "暂未获取",
            "market_cap": market_cap,
            "float_market_cap": ((_as_float(a_quote.get("float_market_cap_yi")) or 0) * 100000000 if a_quote.get("float_market_cap_yi") else (price * float_shares if price and float_shares else None)),
            "shares_outstanding": shares,
            "float_shares": float_shares,
            "latest_price": price,
            "employees": info.get("fullTimeEmployees"),
            "updated_at": datetime.now().strftime("%Y-%m-%d"),
            "data_source": " + ".join(dict.fromkeys(data_sources)),
        }
        valuation_source = {
            "marketCap": market_cap,
            "trailingPE": a_quote.get("pe_ttm") or info.get("trailingPE"),
            "forwardPE": info.get("forwardPE"),
            "priceToBook": a_quote.get("pb") or info.get("priceToBook"),
            "priceToSalesTrailing12Months": info.get("priceToSalesTrailing12Months"),
            "dividendYield": info.get("dividendYield"),
            "returnOnEquity": info.get("returnOnEquity"),
            "returnOnAssets": info.get("returnOnAssets"),
            "debtToEquity": info.get("debtToEquity"),
            "totalRevenue": info.get("totalRevenue"),
            "currentPrice": price,
            "sharesOutstanding": shares,
            "pe_static": a_quote.get("pe_static"),
            "turnover_pct": a_quote.get("turnover_pct"),
            "limit_up": a_quote.get("limit_up"),
            "limit_down": a_quote.get("limit_down"),
        }
        errors = list(y.get("errors", [])) + list(ak_payload.get("errors", [])) + list(a_stock_payload.get("errors", [])) + list(cn_profile.get("errors", [])) + list(sector_payload.get("errors", []))
        return {
            "profile": profile,
            "annual": y.get("annual", pd.DataFrame()),
            "quarterly": y.get("quarterly", pd.DataFrame()),
            "valuation_source": valuation_source,
            "a_stock_data": a_stock_payload,
            "sector": sector_payload,
            "errors": errors,
        }
