from __future__ import annotations

from .base_provider import BaseProvider, ProviderResult
from ..cache_utils import FileCache, safe_fetch

try:
    import efinance as ef
except Exception:  # pragma: no cover
    ef = None


class EFinanceProvider(BaseProvider):
    name = "efinance"

    def __init__(self, cache: FileCache | None = None):
        self.cache = cache or FileCache("data/cache")

    def get_industry_info(self, code: str, **kwargs) -> ProviderResult:
        if ef is None:
            return ProviderResult(source=self.name, warnings=[{"source": self.name, "interface": "get_belong_board", "error_type": "ImportError", "message": "efinance 未安装"}])
        data, errors = safe_fetch(self.name, "get_belong_board", lambda: ef.stock.get_belong_board(code), retries=2, min_interval=0.8, cache=self.cache)
        return ProviderResult(data=data, source=self.name, warnings=errors)

    def get_realtime_quote(self, code: str, **kwargs) -> ProviderResult:
        if ef is None:
            return ProviderResult(source=self.name, warnings=[{"source": self.name, "interface": "get_latest_quote", "error_type": "ImportError", "message": "efinance 未安装"}])
        data, errors = safe_fetch(self.name, "get_latest_quote", lambda: ef.stock.get_latest_quote(code), retries=1, min_interval=0.8, cache=self.cache)
        return ProviderResult(data=data, source=self.name, warnings=errors)
