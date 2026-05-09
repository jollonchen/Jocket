from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

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

    def fetch(self, code: str, latest_price: float | None = None) -> dict:
        yahoo_code = normalize_a_share_code(code)
        ticker = display_code(yahoo_code)
        y = self._fetch_yfinance(yahoo_code, latest_price)
        ak_payload = self._fetch_akshare(ticker)
        sector_payload = SectorFetcher(self.config).fetch(ticker)
        return self._merge_payload(ticker, yahoo_code, y, ak_payload, sector_payload, latest_price)

    def _fetch_yfinance(self, yahoo_code: str, latest_price: float | None) -> dict:
        errors = []
        info = {}
        annual = pd.DataFrame()
        quarterly = pd.DataFrame()
        try:
            ticker = yf.Ticker(yahoo_code)
            try:
                info = ticker.info or {}
            except Exception as exc:
                errors.append(f"yfinance info失败：{exc}")
            try:
                annual = _statement_to_records(ticker.income_stmt, ticker.balance_sheet, ticker.cashflow, 5)
            except Exception as exc:
                errors.append(f"yfinance 年度财务失败：{exc}")
            try:
                quarterly = _statement_to_records(ticker.quarterly_income_stmt, ticker.quarterly_balance_sheet, ticker.quarterly_cashflow, 12)
            except Exception as exc:
                errors.append(f"yfinance 季度财务失败：{exc}")
        except Exception as exc:
            errors.append(f"yfinance整体失败：{exc}")
        return {"info": info, "annual": annual, "quarterly": quarterly, "errors": errors}

    def _fetch_akshare(self, ticker: str) -> dict:
        out = {"info": {}, "errors": []}
        if ak is None:
            out["errors"].append("AkShare未安装")
            return out
        try:
            df = ak.stock_individual_info_em(symbol=ticker)
            if df is not None and not df.empty and {"item", "value"}.issubset(df.columns):
                out["info"] = dict(zip(df["item"], df["value"]))
        except Exception as exc:
            out["errors"].append(f"AkShare 财务/公司资料获取失败：{exc}")
        return out

    def _market_name(self, ticker: str, yahoo_code: str) -> tuple[str, str]:
        if yahoo_code.endswith(".SS"):
            if ticker.startswith("688"):
                return "上交所", "科创板"
            return "上交所", "沪市"
        if yahoo_code.endswith(".SZ"):
            if ticker.startswith("300"):
                return "深交所", "创业板"
            return "深交所", "深市"
        return "暂未获取", "当前数据源暂不支持"

    def _merge_payload(self, ticker: str, yahoo_code: str, y: dict, ak_payload: dict, sector_payload: dict, latest_price: float | None) -> dict:
        info = y.get("info", {}) or {}
        ak_info = ak_payload.get("info", {}) or {}
        sector_summary = sector_payload.get("summary", {}) or {}
        primary_boards = sector_summary.get("primary_boards", []) or []
        exchange, market = self._market_name(ticker, yahoo_code)
        market_cap = info.get("marketCap")
        shares = info.get("sharesOutstanding")
        float_shares = info.get("floatShares")
        price = latest_price or info.get("currentPrice") or info.get("regularMarketPrice")
        profile = {
            "code": ticker,
            "yahoo_code": yahoo_code,
            "name": ak_info.get("股票简称") or info.get("shortName") or info.get("longName") or ticker,
            "exchange": exchange,
            "market": market,
            "industry": info.get("industry") or "暂未获取",
            "sector": info.get("sector") or "暂未获取",
            "industry_cn": primary_boards[0] if primary_boards else "暂未获取",
            "belong_boards": primary_boards,
            "business": info.get("longBusinessSummary") or "当前数据源暂不支持",
            "list_date": ak_info.get("上市时间") or ak_info.get("上市日期") or "暂未获取",
            "market_cap": market_cap,
            "float_market_cap": price * float_shares if price and float_shares else None,
            "shares_outstanding": shares,
            "float_shares": float_shares,
            "latest_price": price,
            "employees": info.get("fullTimeEmployees"),
            "updated_at": datetime.now().strftime("%Y-%m-%d"),
            "data_source": "yfinance + akshare + efinance" if ak_info else "yfinance + efinance",
        }
        valuation_source = {
            "marketCap": market_cap,
            "trailingPE": info.get("trailingPE"),
            "forwardPE": info.get("forwardPE"),
            "priceToBook": info.get("priceToBook"),
            "priceToSalesTrailing12Months": info.get("priceToSalesTrailing12Months"),
            "dividendYield": info.get("dividendYield"),
            "returnOnEquity": info.get("returnOnEquity"),
            "returnOnAssets": info.get("returnOnAssets"),
            "debtToEquity": info.get("debtToEquity"),
            "totalRevenue": info.get("totalRevenue"),
            "currentPrice": price,
            "sharesOutstanding": shares,
        }
        errors = list(y.get("errors", [])) + list(ak_payload.get("errors", [])) + list(sector_payload.get("errors", []))
        return {
            "profile": profile,
            "annual": y.get("annual", pd.DataFrame()),
            "quarterly": y.get("quarterly", pd.DataFrame()),
            "valuation_source": valuation_source,
            "sector": sector_payload,
            "errors": errors,
        }
