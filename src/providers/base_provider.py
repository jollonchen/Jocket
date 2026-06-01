from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProviderResult:
    data: Any = None
    source: str = ""
    warnings: list[dict | str] = field(default_factory=list)
    from_cache: bool = False


class BaseProvider:
    name = "base"

    def get_price_history(self, code: str, **kwargs) -> ProviderResult:
        return ProviderResult(source=self.name, warnings=["not implemented"])

    def get_realtime_quote(self, code: str, **kwargs) -> ProviderResult:
        return ProviderResult(source=self.name, warnings=["not implemented"])

    def get_company_profile(self, code: str, **kwargs) -> ProviderResult:
        return ProviderResult(source=self.name, warnings=["not implemented"])

    def get_financials(self, code: str, **kwargs) -> ProviderResult:
        return ProviderResult(source=self.name, warnings=["not implemented"])

    def get_valuation_metrics(self, code: str, **kwargs) -> ProviderResult:
        return ProviderResult(source=self.name, warnings=["not implemented"])

    def get_dividends(self, code: str, **kwargs) -> ProviderResult:
        return ProviderResult(source=self.name, warnings=["not implemented"])

    def get_industry_info(self, code: str, **kwargs) -> ProviderResult:
        return ProviderResult(source=self.name, warnings=["not implemented"])

    def get_industry_heat(self, code: str, **kwargs) -> ProviderResult:
        return ProviderResult(source=self.name, warnings=["not implemented"])

    def get_moneyflow(self, code: str, **kwargs) -> ProviderResult:
        return ProviderResult(source=self.name, warnings=["not implemented"])
