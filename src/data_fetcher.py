from __future__ import annotations

from pathlib import Path
from datetime import datetime
import json
import os
import re
import ssl
import urllib.request
import urllib3
import requests
import pandas as pd
import yfinance as yf

from .utils import normalize_a_share_code, display_code, ensure_dirs
from .universe import DEFAULT_UNIVERSE

# Some macOS/Python environments fail on Eastmoney SSL through AkShare, and
# local proxy tools can break Eastmoney requests. Keep this patch so AkShare can
# be used where possible, while the app can still fall back to yfinance.
ssl._create_default_https_context = ssl._create_unverified_context
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def _disable_process_proxies() -> None:
    for key in _PROXY_ENV_KEYS:
        os.environ.pop(key, None)
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"


_disable_process_proxies()

_original_request = requests.request
_original_session_request = requests.sessions.Session.request


def _request_no_verify(method, url, **kwargs):
    kwargs.setdefault("verify", False)
    kwargs.setdefault("proxies", {"http": None, "https": None, "all": None})
    return _original_request(method, url, **kwargs)


def _session_request_no_verify(self, method, url, **kwargs):
    self.trust_env = False
    kwargs.setdefault("verify", False)
    kwargs.setdefault("proxies", {"http": None, "https": None, "all": None})
    return _original_session_request(self, method, url, **kwargs)


requests.request = _request_no_verify
requests.sessions.Session.request = _session_request_no_verify

try:
    import akshare as ak
except Exception:  # pragma: no cover
    ak = None


class DataFetcher:
    """Market data fetcher with selectable providers.

    provider:
    - auto: try Tonghuashun first, then yfinance and AkShare fallback
    - ths: only Tonghuashun
    - akshare: only AkShare
    - yfinance: only Yahoo Finance
    """

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        ensure_dirs()
        self.cache_dir = Path('data/cache')
        self.provider = self.config.get('data', {}).get('provider', 'auto')
        self.adjust = self.config.get('data', {}).get('akshare_adjust', 'qfq')
        self.timeout = float(self.config.get('data', {}).get('timeout', 12))

    def get_universe(self, limit: int | None = None) -> pd.DataFrame:
        df = pd.DataFrame(DEFAULT_UNIVERSE, columns=['name', 'code'])
        df['yahoo_code'] = df['code'].apply(normalize_a_share_code)
        if limit:
            df = df.head(int(limit))
        return df

    def get_hist(
        self,
        code: str,
        start: str | None = None,
        end: str | None = None,
        use_cache: bool = True,
        provider: str | None = None,
    ) -> pd.DataFrame:
        provider = provider or self.provider
        start = start or self.config.get('market', {}).get('default_start_date', '2024-01-01')
        end = end or datetime.now().strftime('%Y-%m-%d')

        if provider == 'ths':
            return self._get_hist_ths(code, start, end, use_cache)
        if provider == 'akshare':
            return self._get_hist_akshare(code, start, end, use_cache)
        if provider == 'yfinance':
            return self._get_hist_yfinance(code, start, end, use_cache)

        # auto mode: prefer Tonghuashun for A-share data, then fall back.
        errors: list[str] = []
        try:
            return self._get_hist_ths(code, start, end, use_cache)
        except Exception as exc:
            errors.append(f'同花顺失败：{exc}')
        try:
            df = self._get_hist_yfinance(code, start, end, use_cache)
            df.attrs['fallback_warning'] = '；'.join(errors)
            return df
        except Exception as exc:
            errors.append(f'yfinance失败：{exc}')
        try:
            df = self._get_hist_akshare(code, start, end, use_cache)
            df.attrs['fallback_warning'] = '；'.join(errors)
            return df
        except Exception as exc:
            errors.append(f'AkShare失败：{exc}')
            raise RuntimeError('所有数据源均失败：' + ' | '.join(errors)) from exc

    def _cache_path(self, provider: str, code: str, start: str, end: str) -> Path:
        key = f"{provider}_{code}_{start}_{end}.csv".replace('/', '-').replace(':', '-')
        return self.cache_dir / key

    @staticmethod
    def _to_ak_code(code: str) -> str:
        return display_code(normalize_a_share_code(code))

    @staticmethod
    def _to_yyyymmdd(date_str: str) -> str:
        return str(date_str).replace('-', '')

    @staticmethod
    def _to_ths_market(code: str) -> tuple[str, str]:
        ticker = display_code(normalize_a_share_code(code))
        market = 'sh' if ticker.startswith(('5', '6', '9')) else 'sz'
        return market, ticker

    @staticmethod
    def _parse_ths_today(text: str) -> dict | None:
        payload_match = re.search(r'\(\{".+?":(\{.+\})\}\)', text)
        if payload_match:
            try:
                payload = json.loads(payload_match.group(1))
            except Exception:
                payload = {}
            if payload:
                return {
                    'date': payload.get('1'),
                    'open': payload.get('7'),
                    'high': payload.get('8'),
                    'low': payload.get('9'),
                    'close': payload.get('11'),
                    'volume': payload.get('13'),
                    'amount': payload.get('19'),
                    'turnover_rate': payload.get('1968584'),
                }

        data_match = re.search(r'"data":"([^"]+)"', text)
        if not data_match:
            return None
        fields = data_match.group(1).split(',')
        if len(fields) < 5:
            return None
        return {
            'date': fields[0],
            'open': fields[1],
            'high': fields[2],
            'low': fields[3],
            'close': fields[4],
            'volume': fields[5] if len(fields) > 5 else None,
            'amount': fields[6] if len(fields) > 6 else None,
            'turnover_rate': fields[7] if len(fields) > 7 else None,
        }

    @staticmethod
    def _parse_ths_last(text: str) -> list[dict]:
        data_match = re.search(r'"data":"([^"]+)"', text)
        if not data_match:
            return []
        rows = []
        for row in data_match.group(1).split(';'):
            parts = row.split(',')
            if len(parts) < 5 or not parts[0].isdigit():
                continue
            rows.append({
                'date': parts[0],
                'open': parts[1],
                'high': parts[2],
                'low': parts[3],
                'close': parts[4],
                'volume': parts[5] if len(parts) > 5 else None,
                'amount': parts[6] if len(parts) > 6 else None,
                'turnover_rate': parts[7] if len(parts) > 7 else None,
            })
        return rows

    def _fetch_ths_text(self, url: str) -> str:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (stock-picker-ui)',
                'Referer': 'https://q.10jqka.com.cn/',
            },
        )
        with opener.open(req, timeout=self.timeout) as resp:
            raw = resp.read()
        return raw.decode('utf-8', errors='ignore')

    def _get_hist_ths(self, code: str, start: str, end: str, use_cache: bool = True) -> pd.DataFrame:
        market, ticker = self._to_ths_market(code)
        cache_path = self._cache_path('ths', ticker, start, end)
        if use_cache and cache_path.exists():
            df = pd.read_csv(cache_path, parse_dates=['date'])
            if not df.empty:
                return df

        last_url = f'https://d.10jqka.com.cn/v2/line/{market}_{ticker}/01/last.js'
        today_url = f'https://d.10jqka.com.cn/v2/line/{market}_{ticker}/01/today.js'
        rows = self._parse_ths_last(self._fetch_ths_text(last_url))

        try:
            today = self._parse_ths_today(self._fetch_ths_text(today_url))
        except Exception:
            today = None
        if today and today.get('date'):
            rows = [row for row in rows if row.get('date') != today.get('date')]
            rows.append(today)

        if not rows:
            raise ValueError(f'同花顺没有获取到行情数据：{ticker}')

        df = pd.DataFrame(rows)
        df['date'] = pd.to_datetime(df['date'], format='%Y%m%d', errors='coerce')
        for col in ['open', 'high', 'low', 'close', 'volume', 'amount', 'turnover_rate']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.dropna(subset=['date', 'close']).sort_values('date')
        start_ts = pd.to_datetime(start)
        end_ts = pd.to_datetime(end)
        df = df[(df['date'] >= start_ts) & (df['date'] <= end_ts)]
        if df.empty:
            raise ValueError(f'同花顺没有获取到指定区间行情数据：{ticker}')
        df['pct_chg'] = df['close'].pct_change() * 100
        if 'amount' not in df.columns:
            df['amount'] = df['close'] * df.get('volume', 0)
        df['amount_est'] = df['amount']
        df['data_source'] = 'ths'
        df['yahoo_code'] = normalize_a_share_code(code)
        if use_cache:
            df.to_csv(cache_path, index=False, encoding='utf-8-sig')
        return df

    def _get_hist_akshare(self, code: str, start: str, end: str, use_cache: bool = True) -> pd.DataFrame:
        if ak is None:
            raise RuntimeError('未安装 akshare，请先执行：pip install akshare')
        ak_code = self._to_ak_code(code)
        cache_path = self._cache_path('akshare', ak_code, start, end)
        if use_cache and cache_path.exists():
            df = pd.read_csv(cache_path, parse_dates=['date'])
            if not df.empty:
                return df

        raw = ak.stock_zh_a_hist(
            symbol=ak_code,
            period='daily',
            start_date=self._to_yyyymmdd(start),
            end_date=self._to_yyyymmdd(end),
            adjust=self.adjust,
        )
        if raw is None or raw.empty:
            raise ValueError(f'AkShare没有获取到行情数据：{ak_code}')

        col_map = {
            '日期': 'date', '开盘': 'open', '最高': 'high', '最低': 'low', '收盘': 'close',
            '成交量': 'volume', '成交额': 'amount', '振幅': 'amplitude', '涨跌幅': 'pct_chg',
            '涨跌额': 'change', '换手率': 'turnover_rate',
        }
        df = raw.rename(columns=col_map).copy()
        keep = [c for c in ['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg', 'turnover_rate'] if c in df.columns]
        df = df[keep]
        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        for c in ['open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg', 'turnover_rate']:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors='coerce')
        df = df.dropna(subset=['date', 'close']).sort_values('date')
        if 'amount' not in df.columns:
            df['amount'] = df['close'] * df.get('volume', 0)
        df['amount_est'] = df['amount']
        df['data_source'] = 'akshare'
        df['yahoo_code'] = normalize_a_share_code(code)
        if use_cache:
            df.to_csv(cache_path, index=False, encoding='utf-8-sig')
        return df

    def _get_hist_yfinance(self, code: str, start: str, end: str, use_cache: bool = True) -> pd.DataFrame:
        yahoo_code = normalize_a_share_code(code)
        cache_path = self._cache_path('yfinance', yahoo_code, start, end)
        if use_cache and cache_path.exists():
            df = pd.read_csv(cache_path, parse_dates=['date'])
            if not df.empty:
                return df

        raw = yf.download(
            yahoo_code,
            start=start,
            end=end,
            progress=False,
            auto_adjust=False,
            threads=False,
        )
        if raw is None or raw.empty:
            raise ValueError(f'yfinance没有获取到行情数据：{yahoo_code}')

        raw = raw.reset_index()
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]

        col_map = {
            'Date': 'date', 'Open': 'open', 'High': 'high', 'Low': 'low',
            'Close': 'close', 'Adj Close': 'adj_close', 'Volume': 'volume'
        }
        df = raw.rename(columns=col_map)
        keep = [c for c in ['date', 'open', 'high', 'low', 'close', 'adj_close', 'volume'] if c in df.columns]
        df = df[keep].copy()
        for c in ['open', 'high', 'low', 'close', 'adj_close', 'volume']:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors='coerce')
        df = df.dropna(subset=['date', 'close']).sort_values('date')
        df['amount_est'] = df['close'] * df.get('volume', 0)
        df['data_source'] = 'yfinance'
        df['yahoo_code'] = yahoo_code
        if use_cache:
            df.to_csv(cache_path, index=False, encoding='utf-8-sig')
        return df
