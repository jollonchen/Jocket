from __future__ import annotations

from .akshare_provider import AkShareProvider
from .a_stock_data_provider import AStockDataProvider
from .base_provider import ProviderResult
from .cached_provider import CachedProvider
from .efinance_provider import EFinanceProvider
from .yfinance_provider import YFinanceProvider
from ..cache_utils import FileCache


class ProviderRouter:
    """Small routing layer for multi-source data with warnings and field provenance.

    The current app still uses specialized fetchers for most transforms; this router
    centralizes provider priority and is intentionally lightweight so those fetchers can
    migrate endpoint-by-endpoint without a risky rewrite.
    """

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.cache = FileCache("data/cache")
        self.providers = {
            "a_stock_data": AStockDataProvider(self.cache, self.config),
            "cache": CachedProvider(self.cache),
            "efinance": EFinanceProvider(self.cache),
            "akshare": AkShareProvider(self.cache),
            "yfinance": YFinanceProvider(self.cache),
        }

    def first_success(self, method: str, code: str, priority: list[str]) -> ProviderResult:
        warnings = []
        for name in priority:
            provider = self.providers[name]
            result = getattr(provider, method)(code)
            warnings.extend(result.warnings)
            data = result.data
            is_empty = data is None or (hasattr(data, "empty") and data.empty)
            if not is_empty:
                result.warnings = warnings
                return result
        return ProviderResult(source="none", warnings=warnings)

    def get_company_profile(self, code: str) -> ProviderResult:
        return self.first_success("get_company_profile", code, ["cache", "a_stock_data", "akshare", "yfinance"])

    def get_industry_info(self, code: str) -> ProviderResult:
        return self.first_success("get_industry_info", code, ["cache", "akshare", "efinance"])

    def get_industry_heat(self, code: str) -> ProviderResult:
        return self.first_success("get_industry_heat", code, ["akshare", "efinance"])

    def get_valuation_metrics(self, code: str) -> ProviderResult:
        return self.first_success("get_valuation_metrics", code, ["a_stock_data", "yfinance"])

    def get_moneyflow(self, code: str) -> ProviderResult:
        return self.first_success("get_moneyflow", code, ["a_stock_data", "akshare"])

    def stock_signal_bundle(self, code: str, trade_date: str | None = None) -> dict:
        provider = self.providers["a_stock_data"]
        return provider.stock_signal_bundle(code, trade_date=trade_date)

    def market_signal_bundle(self, trade_date: str | None = None) -> dict:
        provider = self.providers["a_stock_data"]
        return provider.market_signal_bundle(trade_date=trade_date)
