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

# Global cache instance
_cache = get_cache()


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
    cache_key = f"{ticker}_{start_date}_{end_date}"
    if cached_data := _cache.get_prices(cache_key):
        return [Price(**price) for price in cached_data]

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
            prices.append(Price(
                open=float(row["open"]),
                close=float(row["close"]),
                high=float(row["high"]),
                low=float(row["low"]),
                volume=int(row["volume"]),
                time=date_str
            ))
        
        if prices:
            _cache.set_prices(cache_key, [p.model_dump() for p in prices])
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
    cache_key = f"{ticker}_{period}_{end_date}_{limit}"
    if cached_data := _cache.get_financial_metrics(cache_key):
        return [FinancialMetrics(**metric) for metric in cached_data]

    try:
        from src.fundamental_fetcher import FundamentalFetcher
        fetcher = FundamentalFetcher()
        ticker_clean = normalize_a_share_code(ticker)
        payload = fetcher.fetch(ticker_clean)
        
        profile = payload.get("profile", {})
        valuation = payload.get("valuation_source", {})
        df_statements = payload.get("quarterly" if period == "ttm" else "annual", pd.DataFrame())
        
        latest_stmt = df_statements.iloc[0] if df_statements is not None and not df_statements.empty else {}
        
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

        metrics = FinancialMetrics(
            ticker=ticker,
            report_period=end_date,
            period=period,
            currency="CNY" if ticker_clean.endswith((".SS", ".SZ")) else "USD",
            market_cap=profile.get("market_cap"),
            enterprise_value=profile.get("market_cap"),  # proxy
            price_to_earnings_ratio=valuation.get("pe_ttm") or valuation.get("trailingPE") or valuation.get("pe_static"),
            price_to_book_ratio=valuation.get("pb") or valuation.get("priceToBook"),
            price_to_sales_ratio=valuation.get("priceToSalesTrailing12Months"),
            enterprise_value_to_ebitda_ratio=None,
            enterprise_value_to_revenue_ratio=None,
            free_cash_flow_yield=None,
            peg_ratio=None,
            gross_margin=get_val(latest_stmt, "grossMargin"),
            operating_margin=None,
            net_margin=get_val(latest_stmt, "netMargin"),
            return_on_equity=get_val(latest_stmt, "roe"),
            return_on_assets=get_val(latest_stmt, "roa"),
            return_on_invested_capital=get_val(latest_stmt, "roe"),  # proxy
            asset_turnover=None,
            inventory_turnover=None,
            receivables_turnover=None,
            days_sales_outstanding=None,
            operating_cycle=None,
            working_capital_turnover=None,
            current_ratio=None,
            quick_ratio=None,
            cash_ratio=None,
            operating_cash_flow_ratio=None,
            debt_to_equity=get_val(latest_stmt, "debtToEquity"),
            debt_to_assets=None,
            interest_coverage=None,
            revenue_growth=None,
            earnings_growth=None,
            book_value_growth=None,
            earnings_per_share_growth=None,
            free_cash_flow_growth=None,
            operating_income_growth=None,
            ebitda_growth=None,
            payout_ratio=None,
            earnings_per_share=get_val(latest_stmt, "eps"),
            book_value_per_share=get_val(latest_stmt, "bvps"),
            free_cash_flow_per_share=None
        )
        
        financial_metrics = [metrics]
        _cache.set_financial_metrics(cache_key, [m.model_dump() for m in financial_metrics])
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
        
        df_statements = payload.get("quarterly" if period == "ttm" else "annual", pd.DataFrame())
        if df_statements.empty:
            return []

        # Sort periods in reverse chronological order
        df_statements = df_statements.sort_values("period", ascending=False)
        
        # Filter statements up to end_date
        import pandas as pd
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
                "current_assets": "totalAssets",  # proxy
                "current_liabilities": "totalLiab",  # proxy
                "outstanding_shares": None,
                "dividends_and_other_cash_distributions": None,
                "free_cash_flow": "freeCashFlow",
                "ebit": None,
                "ebitda": None,
                "operating_income": None,
                "total_debt": "totalLiab",  # proxy
                "cash_and_cash_equivalents": "operatingCashFlow"  # proxy
            }
            
            for item in line_items:
                mapped_field = mapping_dict.get(item)
                val = None
                if mapped_field and mapped_field in row:
                    val = row[mapped_field]
                    if pd.isna(val):
                        val = None
                
                if val is not None:
                    try:
                        val = float(val)
                    except:
                        pass
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
    cache_key = f"{ticker}_{start_date or 'none'}_{end_date}_{limit}"
    if cached_data := _cache.get_company_news(cache_key):
        return [CompanyNews(**news) for news in cached_data]

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
        _cache.set_company_news(cache_key, [news.model_dump() for news in all_news])
    return all_news


def get_market_cap(
    ticker: str,
    end_date: str,
    api_key: str = None,
) -> float | None:
    """Fetch market cap using yfinance."""
    try:
        import yfinance as yf
        ticker_clean = normalize_a_share_code(ticker)
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
