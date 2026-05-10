from __future__ import annotations

import yfinance as yf

from .base_provider import BaseProvider, ProviderResult
from ..cache_utils import FileCache, safe_fetch
from ..utils import normalize_a_share_code


class YFinanceProvider(BaseProvider):
    name = "yfinance"

    def __init__(self, cache: FileCache | None = None):
        self.cache = cache or FileCache("data/cache")

    def get_company_profile(self, code: str, **kwargs) -> ProviderResult:
        yahoo_code = normalize_a_share_code(code)
        ticker = yf.Ticker(yahoo_code)
        data, errors = safe_fetch(self.name, "ticker.info", lambda: ticker.info or {}, retries=2, min_interval=0.8, cache=self.cache)
        return ProviderResult(data=data, source=self.name, warnings=errors)

    def get_financials(self, code: str, **kwargs) -> ProviderResult:
        yahoo_code = normalize_a_share_code(code)
        ticker = yf.Ticker(yahoo_code)
        data, errors = safe_fetch(
            self.name,
            "financials",
            lambda: {"income": ticker.income_stmt, "balance": ticker.balance_sheet, "cashflow": ticker.cashflow},
            retries=1,
            min_interval=0.8,
            cache=self.cache,
        )
        return ProviderResult(data=data, source=self.name, warnings=errors)
