from __future__ import annotations

from .data_fetcher import DataFetcher
from .indicators import add_indicators
from .factor_engine import FactorEngine
from .report_generator import ReportGenerator
from .utils import normalize_a_share_code, display_code


class StockAnalyzer:
    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.fetcher = DataFetcher(config)
        self.engine = FactorEngine(config)
        self.reporter = ReportGenerator()

    def analyze(self, code: str, name: str | None = None, start: str | None = None) -> tuple[dict, object, str]:
        ycode = normalize_a_share_code(code)
        hist = self.fetcher.get_hist(ycode, start=start)
        hist = add_indicators(hist)
        score = self.engine.score(hist)
        report_path = self.reporter.save_analysis_markdown(ycode, name or display_code(ycode), score, hist)
        return score, hist, str(report_path)
