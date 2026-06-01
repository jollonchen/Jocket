import datetime
import logging
import os
import pandas as pd
import time

logger = logging.getLogger(__name__)

from src.utils import normalize_a_share_code
from src.hedge_src.data.cache import get_cache
from src.hedge_src.data.models import (
    CompanyNews,
    CompanyNewsResponse,
    FinancialMetrics,
    FinancialMetricsResponse,
    Price,
    PriceResponse,
    LineItem,
    LineItemResponse,
    InsiderTrade,
    InsiderTradeResponse,
    CompanyFactsResponse,
)
from src.hedge_src.utils.numeric import finite_float_or_none

# Global cache instance
_cache = get_cache()


def _safe_float(value):
    return finite_float_or_none(value)


def _clean_nonfinite_values(data: dict) -> dict:
    cleaned = {}
    for key, value in data.items():
        if isinstance(value, float):
            cleaned[key] = finite_float_or_none(value)
        else:
            cleaned[key] = value
    return cleaned


def _is_a_share_ticker(ticker: str) -> bool:
    ticker_clean = normalize_a_share_code(ticker)
    return ticker_clean.endswith((".SS", ".SZ"))


def _growth_compare_offset(period: str, available_rows: int) -> int:
    """Use YoY for quarterly A-share data when possible; otherwise use prior annual period."""
    if period == "ttm" and available_rows >= 5:
        return 4
    return 1


# Yahoo Finance mapping dictionary for standard line items
YF_MAP = {
    "revenue": ["Total Revenue", "Operating Revenue"],
    "net_income": ["Net Income", "Net Income Common Stockholders"],
    "earnings_per_share": ["Basic EPS", "Diluted EPS"],
    "book_value_per_share": ["Book Value Per Share"],
    "total_assets": ["Total Assets"],
    "total_liabilities": ["Total Liabilities Net Minority Interest", "Total Liabilities"],
    "current_assets": ["Current Assets"],
    "current_liabilities": ["Current Liabilities"],
    "outstanding_shares": ["Basic Average Shares", "Diluted Average Shares"],
    "dividends_and_other_cash_distributions": ["Cash Dividends Paid", "Common Stock Dividend Paid"],
    "free_cash_flow": ["Free Cash Flow"],
    "ebit": ["EBIT"],
    "ebitda": ["EBITDA"],
    "operating_income": ["Operating Income"],
    "total_debt": ["Total Debt"],
    "cash_and_cash_equivalents": ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"]
}


def _make_api_request(url: str, headers: dict, method: str = "GET", json_data: dict = None, max_retries: int = 3):
    """Fallback legacy helper (not used by yfinance)."""
    import requests
    for attempt in range(max_retries + 1):
        if method.upper() == "POST":
            response = requests.post(url, headers=headers, json=json_data)
        else:
            response = requests.get(url, headers=headers)
        if response.status_code == 429 and attempt < max_retries:
            delay = 60 + (30 * attempt)
            time.sleep(delay)
            continue
        return response


def get_prices(ticker: str, start_date: str, end_date: str, api_key: str = None) -> list[Price]:
    """Fetch price data from cache or Jocket's robust DataFetcher."""
    # Check cache by ticker instead of compound key to leverage prefetched data
    cached_data = _cache.get_prices(ticker)
    if cached_data:
        filtered = [p for p in cached_data if start_date <= p["time"] <= end_date]
        cached_times = [p["time"] for p in cached_data]
        if cached_times:
            min_time = min(cached_times)
            max_time = max(cached_times)
            if min_time <= start_date and end_date <= max_time:
                return [Price(**price) for price in filtered]

    try:
        from src.data_fetcher import DataFetcher
        fetcher = DataFetcher()
        ticker_clean = normalize_a_share_code(ticker)
        df = fetcher.get_hist(ticker_clean, start=start_date, end=end_date)
        if df.empty:
            return []

        prices = []
        for index, row in df.iterrows():
            # Check if index is date, or if it is a column
            dt = row["date"] if "date" in df.columns else index
            date_str = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)
            open_price = _safe_float(row.get("open"))
            close_price = _safe_float(row.get("close"))
            high_price = _safe_float(row.get("high"))
            low_price = _safe_float(row.get("low"))
            volume = _safe_float(row.get("volume"))
            if None in (open_price, close_price, high_price, low_price, volume):
                continue
            prices.append(Price(
                open=open_price,
                close=close_price,
                high=high_price,
                low=low_price,
                volume=int(volume),
                time=date_str
            ))

        if prices:
            _cache.set_prices(ticker, [p.model_dump() for p in prices])
        return prices
    except Exception as e:
        logger.warning("Failed to fetch price data using DataFetcher for %s: %s", ticker, e)
        return []



def get_financial_metrics(
    ticker: str,
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
    api_key: str = None,
) -> list[FinancialMetrics]:
    """Fetch financial metrics from cache or Jocket's robust FundamentalFetcher."""
    # Check cache by ticker to avoid dynamic end_date misses
    cached_data = _cache.get_financial_metrics(ticker)
    if cached_data:
        filtered = [
            m for m in cached_data
            if m.get("period") == period and m.get("report_period") <= end_date
        ]
        if filtered:
            filtered = sorted(filtered, key=lambda x: x["report_period"], reverse=True)
            for metric in filtered:
                source_quality = metric.get("source_quality")
                if isinstance(source_quality, dict):
                    source_quality["proxy_fields"] = [item for item in source_quality.get("proxy_fields", []) if item]
            return [FinancialMetrics(**metric) for metric in filtered[:limit]]

    try:
        from src.fundamental_fetcher import FundamentalFetcher
        fetcher = FundamentalFetcher()
        ticker_clean = normalize_a_share_code(ticker)
        payload = fetcher.fetch(ticker_clean)

        profile = payload.get("profile", {})
        valuation = payload.get("valuation_source", {})
        df_statements = payload.get("quarterly" if period == "ttm" else "annual", pd.DataFrame())

        if df_statements is None or df_statements.empty:
            return []

        # Sort and filter statements by end_date
        df_statements = df_statements.sort_values("period", ascending=False)
        end_dt = pd.to_datetime(end_date)
        df_statements["dt"] = pd.to_datetime(df_statements["period"])
        df_statements = df_statements[df_statements["dt"] <= end_dt]
        compare_offset = _growth_compare_offset(period, len(df_statements))
        df_statements = df_statements.head(max(limit, limit + compare_offset))

        if df_statements.empty:
            return []

        # Safely obtain statements attributes
        def get_val(df_val, field_name):
            if isinstance(df_val, dict):
                return df_val.get(field_name)
            elif hasattr(df_val, "get"):
                try:
                    return df_val.get(field_name)
                except Exception:
                    pass
            return None

        financial_metrics = []
        rows_list = list(df_statements.iterrows())
        for i, (idx, row) in enumerate(rows_list[:limit]):
            net_marg = get_val(row, "netMargin")
            gross_marg = get_val(row, "grossMargin")
            operating_marg = get_val(row, "operatingMargin") or net_marg

            # Growth rates by comparing with older period (i + 1)
            rev_growth = None
            earn_growth = None
            eps_growth = None
            fcf_growth = None

            compare_idx = i + compare_offset
            if compare_idx < len(rows_list):
                _, prev_row = rows_list[compare_idx]
                prev_rev = get_val(prev_row, "totalRevenue")
                prev_net = get_val(prev_row, "netIncome")
                prev_eps = get_val(prev_row, "eps")
                prev_fcf = get_val(prev_row, "freeCashFlow")

                curr_rev = get_val(row, "totalRevenue")
                curr_net = get_val(row, "netIncome")
                curr_eps = get_val(row, "eps")
                curr_fcf = get_val(row, "freeCashFlow")

                if prev_rev and prev_rev != 0 and curr_rev is not None:
                    rev_growth = (curr_rev - prev_rev) / abs(prev_rev)
                if prev_net and prev_net != 0 and curr_net is not None:
                    earn_growth = (curr_net - prev_net) / abs(prev_net)
                if prev_eps and prev_eps != 0 and curr_eps is not None:
                    eps_growth = (curr_eps - prev_eps) / abs(prev_eps)
                if prev_fcf and prev_fcf != 0 and curr_fcf is not None:
                    fcf_growth = (curr_fcf - prev_fcf) / abs(prev_fcf)

            # Calculate current_ratio if currentAssets and currentLiabilities are available
            curr_assets = get_val(row, "currentAssets")
            curr_liabs = get_val(row, "currentLiabilities")
            current_ratio = None
            if curr_assets and curr_liabs and curr_liabs != 0:
                current_ratio = curr_assets / curr_liabs

            # Calculate FCF yield
            mcap = profile.get("market_cap")
            fcf_yield = None
            curr_fcf = get_val(row, "freeCashFlow")
            if curr_fcf and mcap and mcap != 0:
                fcf_yield = curr_fcf / mcap

            # Estimate PEG ratio
            peg_ratio = None
            pe = valuation.get("pe_ttm") or valuation.get("trailingPE") or valuation.get("pe_static")
            if pe and eps_growth and eps_growth > 0:
                peg_ratio = pe / (eps_growth * 100)

            ebit = get_val(row, "ebit") or get_val(row, "operatingIncome") or get_val(row, "netIncome")
            ebitda = get_val(row, "ebitda") or ebit
            interest_expense = get_val(row, "interestExpense")
            beta = profile.get("beta")
            revenue = get_val(row, "totalRevenue")
            assets = get_val(row, "totalAssets")
            total_liab = get_val(row, "totalLiab")
            shares = _safe_float(get_val(row, "outstandingShares") or profile.get("shares_outstanding") or valuation.get("sharesOutstanding"))
            fcf_per_share = curr_fcf / shares if curr_fcf and shares else None
            debt_to_assets = total_liab / assets if total_liab and assets else None
            interest_coverage = None
            if ebit and interest_expense and interest_expense != 0:
                interest_coverage = abs(ebit / interest_expense)

            ev_to_ebit = None
            curr_net_income = get_val(row, "netIncome")
            if pe and ebit and curr_net_income and ebit != 0:
                ev_to_ebit = pe * (curr_net_income / ebit)

            proxy_fields = [
                "enterprise_value=market_cap" if profile.get("market_cap") else None,
                "return_on_invested_capital=roe" if get_val(row, "roe") is not None else None,
                "ebit=operatingIncome/netIncome fallback" if ebit is not None and get_val(row, "ebit") is None else None,
            ]

            metric_payload = {
                "ticker": ticker,
                "report_period": row["period"],
                "period": period,
                "currency": "CNY" if ticker_clean.endswith((".SS", ".SZ")) else "USD",
                "market_cap": profile.get("market_cap"),
                "enterprise_value": profile.get("market_cap"),  # proxy
                "price_to_earnings_ratio": pe,
                "price_to_book_ratio": valuation.get("pb") or valuation.get("priceToBook"),
                "price_to_sales_ratio": valuation.get("priceToSalesTrailing12Months"),
                "enterprise_value_to_ebitda_ratio": None,
                "enterprise_value_to_revenue_ratio": None,
                "free_cash_flow_yield": fcf_yield,
                "peg_ratio": peg_ratio,
                "gross_margin": gross_marg,
                "operating_margin": operating_marg,
                "net_margin": net_marg,
                "return_on_equity": get_val(row, "roe"),
                "return_on_assets": get_val(row, "roa"),
                "return_on_invested_capital": get_val(row, "roe"),  # proxy
                "asset_turnover": revenue / assets if revenue and assets else None,
                "inventory_turnover": None,
                "receivables_turnover": None,
                "days_sales_outstanding": None,
                "operating_cycle": None,
                "working_capital_turnover": None,
                "current_ratio": current_ratio,
                "quick_ratio": None,
                "cash_ratio": None,
                "operating_cash_flow_ratio": None,
                "debt_to_equity": get_val(row, "debtToEquity"),
                "debt_to_assets": debt_to_assets,
                "interest_coverage": interest_coverage,
                "revenue_growth": rev_growth,
                "earnings_growth": earn_growth,
                "book_value_growth": None,
                "earnings_per_share_growth": eps_growth,
                "free_cash_flow_growth": fcf_growth,
                "operating_income_growth": None,
                "ebitda_growth": None,
                "payout_ratio": None,
                "earnings_per_share": get_val(row, "eps"),
                "book_value_per_share": get_val(row, "bvps"),
                "free_cash_flow_per_share": fcf_per_share,
                "ebit": ebit,
                "ebitda": ebitda,
                "interest_expense": interest_expense,
                "beta": beta,
                "ev_to_ebit": ev_to_ebit,
                "source_quality": {
                    "data_sources": profile.get("data_source"),
                    "growth_basis": "同比" if compare_offset == 4 else "相邻报告期",
                    "proxy_fields": [item for item in proxy_fields if item],
                    "missing_fields": [
                        field for field, value in {
                            "current_ratio": current_ratio,
                            "free_cash_flow_per_share": fcf_per_share,
                            "interest_coverage": interest_coverage,
                            "beta": beta,
                        }.items() if value is None
                    ],
                },
            }
            metrics = FinancialMetrics(**_clean_nonfinite_values(metric_payload))
            financial_metrics.append(metrics)

        if financial_metrics:
            _cache.set_financial_metrics(ticker, [m.model_dump() for m in financial_metrics])
        return financial_metrics
    except Exception as e:
        logger.warning("Failed to fetch financial metrics using FundamentalFetcher for %s: %s", ticker, e)
        return []



def search_line_items(
    ticker: str,
    line_items: list[str],
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
    api_key: str = None,
) -> list[LineItem]:
    """Fetch line items from Jocket's robust FundamentalFetcher."""
    try:
        from src.fundamental_fetcher import FundamentalFetcher
        fetcher = FundamentalFetcher()
        ticker_clean = normalize_a_share_code(ticker)
        payload = fetcher.fetch(ticker_clean)
        profile = payload.get("profile", {}) or {}
        valuation = payload.get("valuation_source", {}) or {}

        df_statements = payload.get("quarterly" if period == "ttm" else "annual", pd.DataFrame())
        if df_statements.empty:
            return []

        # Sort periods in reverse chronological order
        df_statements = df_statements.sort_values("period", ascending=False)

        # Filter statements up to end_date
        end_dt = pd.to_datetime(end_date)
        df_statements["dt"] = pd.to_datetime(df_statements["period"])
        df_statements = df_statements[df_statements["dt"] <= end_dt]
        df_statements = df_statements.head(limit)

        currency = "CNY" if ticker_clean.endswith((".SS", ".SZ")) else "USD"

        results = []
        for idx, row in df_statements.iterrows():
            item_kwargs = {
                "ticker": ticker,
                "report_period": row["period"],
                "period": period,
                "currency": currency
            }

            # Map standard fields from FundamentalFetcher to LineItem Pydantic fields
            mapping_dict = {
                "revenue": "totalRevenue",
                "net_income": "netIncome",
                "earnings_per_share": "eps",
                "book_value_per_share": "bvps",
                "total_assets": "totalAssets",
                "total_liabilities": "totalLiab",
                "current_assets": "currentAssets",
                "current_liabilities": "currentLiabilities",
                "outstanding_shares": "outstandingShares",
                "dividends_and_other_cash_distributions": "dividends",
                "free_cash_flow": "freeCashFlow",
                "ebit": "ebit",
                "ebitda": "ebitda",
                "operating_income": "operatingIncome",
                "total_debt": "totalDebt",
                "cash_and_equivalents": "cashAndEquivalents",
                "cash_and_cash_equivalents": "cashAndEquivalents",
                "shareholders_equity": "totalStockholderEquity",
                "capital_expenditure": "capitalExpenditure",
                "depreciation_and_amortization": "depreciationAndAmortization",
                "issuance_or_purchase_of_equity_shares": "issuance",
                "gross_profit": "grossProfit",
                "research_and_development": "researchDevelopment",
                "operating_expense": "operatingExpense",
                "goodwill_and_intangible_assets": "goodwillAndIntangibleAssets",
                "interest_expense": "interestExpense",
                "gross_margin": "grossMargin",
                "operating_margin": "operatingMargin",
                "return_on_invested_capital": "roe",
            }

            for item in line_items:
                mapped_field = mapping_dict.get(item)
                val = None
                if mapped_field and mapped_field in row:
                    val = row[mapped_field]
                    if pd.isna(val):
                        val = None

                # Dynamic fallbacks and proxies to ensure no data is None/missing for agent logic
                if val is None:
                    if item == "outstanding_shares":
                        val = profile.get("shares_outstanding") or valuation.get("sharesOutstanding")
                    elif item == "ebit":
                        val = row.get("ebit") or row.get("operatingIncome") or row.get("netIncome")
                    elif item == "ebitda":
                        eb = row.get("ebit") or row.get("operatingIncome") or row.get("netIncome") or 0.0
                        dp = row.get("depreciationAndAmortization") or 0.0
                        val = eb + dp if (eb or dp) else None
                    elif item == "operating_income":
                        val = row.get("operatingIncome") or row.get("ebit") or row.get("netIncome")
                    elif item in ("cash_and_equivalents", "cash_and_cash_equivalents"):
                        val = row.get("cashAndEquivalents")
                    elif item == "working_capital":
                        curr_assets = row.get("currentAssets")
                        curr_liabs = row.get("currentLiabilities")
                        if curr_assets is not None and curr_liabs is not None:
                            val = curr_assets - curr_liabs
                    elif item == "current_assets":
                        val = row.get("currentAssets") or row.get("totalAssets")
                    elif item == "current_liabilities":
                        val = row.get("currentLiabilities") or row.get("totalLiab")
                    elif item == "total_debt":
                        val = row.get("totalDebt") or row.get("totalLiab")
                    elif item == "operating_margin":
                        val = row.get("operatingMargin") or row.get("netMargin")
                    elif item == "gross_margin":
                        val = row.get("grossMargin")
                    elif item == "return_on_invested_capital":
                        val = row.get("roe")

                if val is not None:
                    val = _safe_float(val)
                item_kwargs[item] = val

            results.append(LineItem(**item_kwargs))

        return results
    except Exception as e:
        logger.warning("Failed to fetch line items using FundamentalFetcher for %s: %s", ticker, e)
        return []



def get_insider_trades(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
    api_key: str = None,
) -> list[InsiderTrade]:
    """Fetch insider trades (returns empty list for free compatibility)."""
    return []


def get_company_news(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
    api_key: str = None,
) -> list[CompanyNews]:
    """Fetch company news using yfinance, with A-share fallback via Jocket NewsFetcher."""
    # Check cache by ticker instead of compound key to leverage prefetched news
    cached_data = _cache.get_company_news(ticker)
    if cached_data:
        filtered = cached_data
        if start_date:
            filtered = [n for n in filtered if n.get("date") and start_date <= n["date"][:10]]
        if end_date:
            filtered = [n for n in filtered if n.get("date") and n["date"][:10] <= end_date]

        # Check coverage of cached news to avoid empty hits
        cached_dates = [n["date"][:10] for n in cached_data if n.get("date")]
        if cached_dates:
            min_date = min(cached_dates)
            max_date = max(cached_dates)
            if (not start_date or min_date <= start_date) and end_date <= max_date:
                return [CompanyNews(**news) for news in filtered[:limit]]

    all_news: list[CompanyNews] = []
    ticker_clean = normalize_a_share_code(ticker)
    is_a_share = ticker_clean.endswith((".SS", ".SZ"))

    # --- Primary: yfinance (works well for US equities) ---
    if not is_a_share:
        try:
            import yfinance as yf
            yf_ticker = yf.Ticker(ticker_clean)
            yf_news = yf_ticker.news or []

            end_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
            start_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None

            for item in yf_news:
                content = item.get("content", {}) if "content" in item else item

                title = content.get("title", "")
                if not title:
                    continue

                source_info = content.get("provider", {})
                if isinstance(source_info, dict):
                    source = source_info.get("displayName", "Yahoo Finance")
                else:
                    source = content.get("publisher", "Yahoo Finance")

                url = content.get("clickThroughUrl", {}).get("url") if isinstance(content.get("clickThroughUrl"), dict) else None
                if not url:
                    url = content.get("canonicalUrl", {}).get("url") if isinstance(content.get("canonicalUrl"), dict) else None
                if not url:
                    url = content.get("link", "")

                pub_date_str = content.get("pubDate")
                news_date = None
                news_datetime_str = None

                if pub_date_str:
                    try:
                        dt = datetime.datetime.strptime(pub_date_str, "%Y-%m-%dT%H:%M:%SZ")
                        news_date = dt.date()
                        news_datetime_str = pub_date_str
                    except Exception:
                        pass

                if not news_date:
                    pub_time = content.get("providerPublishTime")
                    if pub_time:
                        try:
                            dt = datetime.datetime.fromtimestamp(pub_time)
                            news_date = dt.date()
                            news_datetime_str = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                        except Exception:
                            pass

                if not news_date:
                    continue

                if news_date > end_dt:
                    continue
                if start_dt and news_date < start_dt:
                    continue

                all_news.append(CompanyNews(
                    ticker=ticker,
                    title=title,
                    author=None,
                    source=source,
                    date=news_datetime_str,
                    url=url,
                    sentiment=None
                ))
        except Exception as e:
            logger.warning("Failed to fetch news using yfinance for %s: %s", ticker, e)

    # --- Fallback: Jocket native NewsFetcher for A-shares ---
    if not all_news and is_a_share:
        try:
            from src.news_fetcher import NewsFetcher
            from src.utils import display_code
            fetcher = NewsFetcher()
            code6 = display_code(ticker_clean)
            payload = fetcher.fetch(code6)
            items = payload.get("items", [])
            for item in items[:limit]:
                title = item.get("title", "")
                if not title:
                    continue
                news_date_str = item.get("date")
                all_news.append(CompanyNews(
                    ticker=ticker,
                    title=title,
                    author=None,
                    source=item.get("source", "东方财富"),
                    date=f"{news_date_str}T00:00:00Z" if news_date_str else None,
                    url=item.get("url", ""),
                    sentiment=None,
                ))
        except Exception as e:
            logger.warning("Failed to fetch A-share news using NewsFetcher for %s: %s", ticker, e)

    all_news = all_news[:limit]
    if all_news:
        _cache.set_company_news(ticker, [news.model_dump() for news in all_news])
    return all_news


def get_market_cap(
    ticker: str,
    end_date: str,
    api_key: str = None,
) -> float | None:
    """Fetch market cap using A-share native sources before yfinance."""
    try:
        ticker_clean = normalize_a_share_code(ticker)
        if _is_a_share_ticker(ticker_clean):
            financial_metrics = get_financial_metrics(ticker, end_date, api_key=api_key)
            if financial_metrics and financial_metrics[0].market_cap:
                return financial_metrics[0].market_cap

        import yfinance as yf
        yf_ticker = yf.Ticker(ticker_clean)
        info = yf_ticker.info or {}
        market_cap = info.get("marketCap")
        if market_cap:
            return float(market_cap)

        financial_metrics = get_financial_metrics(ticker, end_date, api_key=api_key)
        if financial_metrics and financial_metrics[0].market_cap:
            return financial_metrics[0].market_cap

        return None
    except Exception as e:
        logger.warning("Failed to fetch market cap using yfinance for %s: %s", ticker, e)
        return None


def prices_to_df(prices: list[Price]) -> pd.DataFrame:
    """Convert prices list to a DataFrame."""
    df = pd.DataFrame([p.model_dump() for p in prices])
    df["Date"] = pd.to_datetime(df["time"])
    df.set_index("Date", inplace=True)
    numeric_cols = ["open", "close", "high", "low", "volume"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.sort_index(inplace=True)
    return df


def get_price_data(ticker: str, start_date: str, end_date: str, api_key: str = None) -> pd.DataFrame:
    """Fetch and return price history DataFrame."""
    prices = get_prices(ticker, start_date, end_date, api_key=api_key)
    return prices_to_df(prices)
