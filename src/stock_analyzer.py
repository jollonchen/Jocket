from __future__ import annotations

import pandas as pd

from .data_fetcher import DataFetcher
from .indicators import add_indicators
from .factor_engine import FactorEngine
from .news_fetcher import NewsFetcher
from .report_generator import ReportGenerator
from .utils import normalize_a_share_code, display_code


class StockAnalyzer:
    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.fetcher = DataFetcher(config)
        self.engine = FactorEngine(config)
        self.news_fetcher = NewsFetcher(config)
        self.reporter = ReportGenerator()

    def analyze(self, code: str, name: str | None = None, start: str | None = None, include_news: bool = True) -> tuple[dict, object, str]:
        ycode = normalize_a_share_code(code)
        
        # Always fetch at least ~260 business days of history to accurately calculate MA250 and scores
        fetch_start = (pd.Timestamp.today().normalize() - pd.offsets.BDay(260)).strftime('%Y-%m-%d')
        if start and start < fetch_start:
            fetch_start = start
            
        full_hist = self.fetcher.get_hist(ycode, start=fetch_start)
        full_hist = add_indicators(full_hist)
        score = self.engine.score(full_hist)
        
        score['code'] = display_code(ycode)
        score['news'] = (
            self.news_fetcher.fetch(ycode, name=name or display_code(ycode))
            if include_news
            else {"available": False, "items": [], "summary": "消息面后置加载", "heat_score": 0, "errors": []}
        )
        
        # The UI always receives a stable 120-trading-day display window. Scores
        # are computed above on the full fetch window, so short chart windows do
        # not blank RSI/MACD/KDJ or trigger "history insufficient" scoring.
        hist = full_hist.tail(120).copy()
        hist.attrs = full_hist.attrs
            
        report_path = self.reporter.save_analysis_markdown(ycode, name or display_code(ycode), score, hist)
        return score, hist, str(report_path)
