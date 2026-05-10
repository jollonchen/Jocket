from __future__ import annotations

import pandas as pd

from .data_fetcher import DataFetcher
from .indicators import add_indicators
from .factor_engine import FactorEngine
from .news_fetcher import NewsFetcher
from .report_generator import ReportGenerator


class StockScreener:
    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.fetcher = DataFetcher(config)
        self.engine = FactorEngine(config)
        self.news_fetcher = NewsFetcher(config)
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

        enrich_n = min(len(df), max(int(top), int(top) * 2))
        df = df.head(enrich_n).copy()
        df = self._enrich_with_news(df)
        sort_col = 'news_adjusted_score' if mode == 'all' and 'news_adjusted_score' in df.columns else (
            'short_score' if mode == 'short' else 'long_score' if mode == 'long' else 'composite_score'
        )
        df = df.sort_values(sort_col, ascending=False).head(int(top)).reset_index(drop=True)
        df.attrs['scanned_count'] = scanned_count
        df.attrs['fetched_count'] = fetched_count
        df.attrs['success_rate'] = fetched_count / scanned_count if scanned_count else 0
        df.attrs['errors'] = errors
        path = self.reporter.save_screen_csv(df, mode)
        return df, str(path)

    def _enrich_with_news(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        rows = []
        for _, row in df.iterrows():
            item = row.to_dict()
            try:
                news = self.news_fetcher.fetch(str(item.get('code')), name=str(item.get('name') or ''))
                heat = float(news.get('heat_score') or 0)
                top_item = (news.get('items') or [{}])[0]
                item['news_heat_score'] = heat
                item['news_top_title'] = top_item.get('title') or news.get('summary')
                item['news_relevance'] = top_item.get('relevance_score') or 0
                item['news_relation_reason'] = top_item.get('relevance_reason') or '暂无高相关公开消息'
                item['news_source'] = news.get('source')
                item['news_adjusted_score'] = round(float(item.get('composite_score') or 0) * 0.88 + heat * 0.12, 1)
            except Exception as exc:
                item['news_heat_score'] = 0
                item['news_top_title'] = ''
                item['news_relevance'] = 0
                item['news_relation_reason'] = f'新闻源暂不可用：{exc}'
                item['news_source'] = ''
                item['news_adjusted_score'] = item.get('composite_score')
            rows.append(item)
        return pd.DataFrame(rows)
