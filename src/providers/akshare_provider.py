from __future__ import annotations

from .base_provider import BaseProvider, ProviderResult
from ..cache_utils import FileCache, safe_fetch

try:
    import akshare as ak
except Exception:  # pragma: no cover
    ak = None


class AkShareProvider(BaseProvider):
    name = "akshare"

    def __init__(self, cache: FileCache | None = None):
        self.cache = cache or FileCache("data/cache")

    def _missing(self, interface: str) -> ProviderResult:
        return ProviderResult(source=self.name, warnings=[{"source": self.name, "interface": interface, "error_type": "ImportError", "message": "AkShare 未安装"}])

    def get_company_profile(self, code: str, **kwargs) -> ProviderResult:
        if ak is None:
            return self._missing("stock_individual_info_em")
        data, errors = safe_fetch(self.name, "stock_individual_info_em", lambda: ak.stock_individual_info_em(symbol=code), retries=1, min_interval=1.5, cache=self.cache)
        return ProviderResult(data=data, source=self.name, warnings=errors)

    def get_industry_heat(self, code: str, **kwargs) -> ProviderResult:
        if ak is None:
            return self._missing("stock_fund_flow_industry")
        data, errors = safe_fetch(self.name, "stock_fund_flow_industry", lambda: ak.stock_fund_flow_industry(symbol="即时"), retries=1, min_interval=1.5, cache=self.cache)
        return ProviderResult(data=data, source=self.name, warnings=errors)

    def get_moneyflow(self, code: str, **kwargs) -> ProviderResult:
        if ak is None:
            return self._missing("stock_individual_fund_flow")
        # AkShare money-flow interfaces vary by version; keep this as a routed optional endpoint.
        return ProviderResult(source=self.name, warnings=[{"source": self.name, "interface": "moneyflow", "message": "当前版本未启用个股资金流接口"}])
