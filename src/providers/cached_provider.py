from __future__ import annotations

from .base_provider import BaseProvider, ProviderResult
from ..cache_utils import FileCache


class CachedProvider(BaseProvider):
    name = "cache"

    def __init__(self, cache: FileCache | None = None):
        self.cache = cache or FileCache("data/cache")

    def get_company_profile(self, code: str, **kwargs) -> ProviderResult:
        data = self.cache.get_pickle("fundamentals", f"fundamental_{code}", ttl_seconds=86400)
        return ProviderResult(data=data, source=self.name, from_cache=bool(data))

    def get_industry_info(self, code: str, **kwargs) -> ProviderResult:
        data = self.cache.get_pickle("industry", f"sector_{code}", ttl_seconds=1800)
        return ProviderResult(data=data, source=self.name, from_cache=bool(data))
