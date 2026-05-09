from __future__ import annotations

import pandas as pd

from .data_fetcher import DataFetcher
from .indicators import add_indicators
from .factor_engine import FactorEngine
from .report_generator import ReportGenerator


class StockScreener:
    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.fetcher = DataFetcher(config)
        self.engine = FactorEngine(config)
        self.reporter = ReportGenerator()

    def screen(self, mode: str = 'all', top: int = 10, limit: int | None = 80, start: str | None = None) -> tuple[pd.DataFrame, str]:
        universe = self.fetcher.get_universe(limit=limit)
        rows = []
        errors = []
        scanned_count = len(universe)
        fetched_count = 0
        for _, item in universe.iterrows():
            try:
                hist = self.fetcher.get_hist(item['yahoo_code'], start=start)
                fetched_count += 1
                if len(hist) < self.config.get('market', {}).get('min_history_days', 120):
                    continue
                hist = add_indicators(hist)
                score = self.engine.score(hist)
                latest = score.get('latest', {})
                rows.append({
                    'name': item['name'],
                    'code': item['code'],
                    'yahoo_code': item['yahoo_code'],
                    'date': latest.get('date'),
                    'close': latest.get('close'),
                    'short_score': score.get('short_score'),
                    'long_score': score.get('long_score'),
                    'composite_score': score.get('composite_score'),
                    'ret_5d': latest.get('ret_5d'),
                    'ret_20d': latest.get('ret_20d'),
                    'rsi14': latest.get('rsi14'),
                    'vol_ratio_20': latest.get('vol_ratio_20'),
                    'data_source': hist['data_source'].iloc[-1] if 'data_source' in hist.columns and len(hist) else '',
                    'risk_flags': '；'.join(score.get('risk_flags', [])),
                    'summary': score.get('summary'),
                })
            except Exception as exc:
                errors.append(f"{item['code']} {item['name']}: {exc}")
                continue
        df = pd.DataFrame(rows)
        if df.empty:
            raise RuntimeError('没有成功获取任何股票数据。请检查网络，或减少/更换股票池。' + ('\n' + '\n'.join(errors[:5]) if errors else ''))
        if mode == 'short':
            df = df.sort_values('short_score', ascending=False)
        elif mode == 'long':
            df = df.sort_values('long_score', ascending=False)
        else:
            df = df.sort_values('composite_score', ascending=False)
        df = df.head(int(top)).reset_index(drop=True)
        df.attrs['scanned_count'] = scanned_count
        df.attrs['fetched_count'] = fetched_count
        df.attrs['success_rate'] = fetched_count / scanned_count if scanned_count else 0
        df.attrs['errors'] = errors
        path = self.reporter.save_screen_csv(df, mode)
        return df, str(path)
