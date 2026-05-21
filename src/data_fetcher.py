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

from .cache_utils import FileCache, safe_fetch
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

try:
    import efinance as ef
except Exception:  # pragma: no cover
    ef = None


class DataFetcher:
    """Market data fetcher with selectable providers.

    provider:
    - auto: try AkShare first, then Tonghuashun and yfinance fallback
    - ths: only Tonghuashun
    - akshare: only AkShare
    - yfinance: only Yahoo Finance
    """

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        ensure_dirs()
        self.cache_dir = Path('data/cache')
        self.file_cache = FileCache(self.cache_dir)
        self.provider = self.config.get('data', {}).get('provider', 'auto')
        self.adjust = self.config.get('data', {}).get('akshare_adjust', 'qfq')
        self.timeout = float(self.config.get('data', {}).get('timeout', 12))
        self.require_realtime = bool(self.config.get('data', {}).get('require_realtime', True))

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
        start = start or self.config.get('market', {}).get('default_start_date')
        if not start:
            start = (pd.Timestamp.today().normalize() - pd.offsets.BDay(180)).strftime('%Y-%m-%d')
        end = end or datetime.now().strftime('%Y-%m-%d')

        if provider == 'ths':
            return self._with_realtime_quote(self._get_hist_ths(code, start, end, use_cache), code, end)
        if provider == 'akshare':
            return self._with_realtime_quote(self._get_hist_akshare(code, start, end, use_cache), code, end)
        if provider == 'yfinance':
            return self._with_realtime_quote(self._get_hist_yfinance(code, start, end, use_cache), code, end)
        if provider == 'efinance':
            return self._with_realtime_quote(self._get_hist_efinance(code, start, end, use_cache), code, end)

        # auto mode: routing based on code pattern
        is_hk = code.endswith('.HK')
        is_us = not code.endswith(('.SS', '.SZ', '.HK')) and not re.search(r'\d{5,6}', code)
        
        errors: list[str] = []
        
        # Route 1: yfinance (best for US, also works for HK)
        if is_us or provider == 'yfinance':
            try:
                return self._with_realtime_quote(self._get_hist_yfinance(code, start, end, use_cache), code, end)
            except Exception as exc:
                errors.append(f'yfinance失败：{exc}')
                if is_us: raise RuntimeError('US股票获取失败：' + str(exc))

        # Route 2: AkShare / efinance / ths (best for A/HK)
        try:
            return self._with_realtime_quote(self._get_hist_akshare(code, start, end, use_cache), code, end)
        except Exception as exc:
            errors.append(f'AkShare失败：{exc}')
            
        try:
            df = self._get_hist_efinance(code, start, end, use_cache)
            return self._with_realtime_quote(df, code, end)
        except Exception as exc:
            errors.append(f'efinance失败：{exc}')
            
        try:
            df = self._get_hist_ths(code, start, end, use_cache)
            return self._with_realtime_quote(df, code, end)
        except Exception as exc:
            errors.append(f'同花顺失败：{exc}')
            
        if not is_us:
            try:
                return self._with_realtime_quote(self._get_hist_yfinance(code, start, end, use_cache), code, end)
            except Exception as exc:
                errors.append(f'yfinance兜底失败：{exc}')
        
        raise RuntimeError('所有数据源均失败：' + ' | '.join(errors))

    def _cache_path(self, provider: str, code: str, start: str, end: str) -> Path:
        adj = self.adjust or "nom"
        key = f"price_{code}_{provider}_{adj}_{start}_{end}.csv".replace('/', '-').replace(':', '-')
        price_dir = self.cache_dir / "price"
        price_dir.mkdir(parents=True, exist_ok=True)
        return price_dir / key

    def _read_price_cache(self, provider: str, code: str, start: str, end: str, ttl_seconds: int = 1800) -> pd.DataFrame | None:
        cache_path = self._cache_path(provider, code, start, end)
        if cache_path.exists() and (datetime.now().timestamp() - cache_path.stat().st_mtime) <= ttl_seconds:
            df = pd.read_csv(cache_path, parse_dates=['date'])
            if not df.empty:
                df.attrs['from_cache'] = True
                return df
        return None

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
    def _to_ak_prefixed_code(code: str) -> str:
        ticker = display_code(normalize_a_share_code(code))
        market = 'sh' if ticker.startswith(('5', '6', '9')) else 'sz'
        return f"{market}{ticker}"

    @staticmethod
    def _to_xq_code(code: str) -> str:
        ticker = display_code(normalize_a_share_code(code))
        market = 'SH' if ticker.startswith(('5', '6', '9')) else 'SZ'
        return f"{market}{ticker}"

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
        if use_cache:
            cached = self._read_price_cache('ths', ticker, start, end, ttl_seconds=1800)
            if cached is not None:
                return cached

        last_url = f'https://d.10jqka.com.cn/v2/line/{market}_{ticker}/01/last.js'
        today_url = f'https://d.10jqka.com.cn/v2/line/{market}_{ticker}/01/today.js'
        text, errors = safe_fetch("ths", "line_last", lambda: self._fetch_ths_text(last_url), retries=2, min_interval=0.8, cache=self.file_cache)
        if text is None:
            raise RuntimeError("同花顺行情接口暂不可用")
        rows = self._parse_ths_last(text)

        try:
            today_text, _ = safe_fetch("ths", "line_today", lambda: self._fetch_ths_text(today_url), retries=1, min_interval=0.8, cache=self.file_cache)
            today = self._parse_ths_today(today_text) if today_text else None
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
        prefixed_code = self._to_ak_prefixed_code(code)
        xq_code = self._to_xq_code(code)
        cache_path = self._cache_path('akshare', ak_code, start, end)
        if use_cache:
            cached = self._read_price_cache('akshare', ak_code, start, end, ttl_seconds=3600)
            if cached is not None:
                return cached

        errors: list[dict] = []
        raw = None
        source_detail = ""
        ak_attempts = []
        if code.endswith('.HK'):
            ak_attempts.append(
                (
                    "stock_hk_hist",
                    lambda: ak.stock_hk_hist(
                        symbol=ak_code,
                        start_date=self._to_yyyymmdd(start),
                        end_date=self._to_yyyymmdd(end),
                        adjust=self.adjust,
                        timeout=self.timeout,
                    ),
                )
            )
        else:
            ak_attempts = [
                (
                    "stock_zh_a_hist_em",
                    lambda: ak.stock_zh_a_hist(
                        symbol=ak_code,
                        period='daily',
                        start_date=self._to_yyyymmdd(start),
                        end_date=self._to_yyyymmdd(end),
                        adjust=self.adjust,
                        timeout=self.timeout,
                    ),
                ),
                (
                    "stock_zh_a_daily_sina",
                    lambda: ak.stock_zh_a_daily(
                        symbol=prefixed_code,
                        start_date=self._to_yyyymmdd(start),
                        end_date=self._to_yyyymmdd(end),
                        adjust=self.adjust,
                    ),
                ),
                (
                    "stock_zh_a_hist_tx",
                    lambda: ak.stock_zh_a_hist_tx(
                        symbol=prefixed_code,
                        start_date=self._to_yyyymmdd(start),
                        end_date=self._to_yyyymmdd(end),
                        adjust=self.adjust,
                        timeout=self.timeout,
                    ),
                ),
            ]
        for interface, fetcher in ak_attempts:
            raw, err = safe_fetch(
                "akshare",
                interface,
                fetcher,
                retries=1,
                min_interval=1.2,
                cache=self.file_cache,
            )
            errors.extend(err)
            if raw is not None and not raw.empty:
                source_detail = interface
                break
        if raw is None and cache_path.exists():
            df = pd.read_csv(cache_path, parse_dates=['date'])
            if not df.empty:
                df.attrs['from_cache'] = True
                df.attrs['fallback_warning'] = "AkShare 实时请求失败，已使用过期缓存"
                return df
        if raw is None or raw.empty:
            raise ValueError(f'AkShare没有获取到行情数据：{ak_code}')

        col_map = {
            '日期': 'date', '开盘': 'open', '最高': 'high', '最低': 'low', '收盘': 'close',
            '成交量': 'volume', '成交额': 'amount', '振幅': 'amplitude', '涨跌幅': 'pct_chg',
            '涨跌额': 'change', '换手率': 'turnover_rate', 'turnover': 'turnover_rate',
        }
        df = raw.rename(columns=col_map).copy()
        keep = [c for c in ['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg', 'turnover_rate'] if c in df.columns]
        df = df[keep]
        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        for c in ['open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg', 'turnover_rate']:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors='coerce')
        df = df.dropna(subset=['date', 'close']).sort_values('date')
        # Volume unit normalization for A-shares:
        # Some sources return Lots (手), others return Shares (股).
        is_a_share = code.endswith(('.SS', '.SZ'))
        if is_a_share:
            # em_hist and tx_hist usually return Hands (Lots). Sina daily usually returns Shares.
            # But the 'source_detail' helps us distinguish.
            if source_detail in ("stock_zh_a_hist_em", "stock_zh_a_hist_tx"):
                 df['volume'] = df['volume'] * 100
            elif source_detail == "stock_zh_a_daily_sina":
                 # Sina daily is already in Shares (股). Do nothing.
                 pass
            else:
                 # Default fallback if unknown, assume Lots if it's very small, 
                 # but it's safer to check the value magnitude or source name.
                 # Let's assume most akshare hist interfaces are Hands.
                 if source_detail != "unknown" and "daily" not in source_detail:
                     df['volume'] = df['volume'] * 100
            
        if 'amount' not in df.columns and 'volume' in df.columns:
            df['amount'] = df['close'] * df.get('volume', 0)
        if 'pct_chg' not in df.columns:
            df['pct_chg'] = df['close'].pct_change() * 100
        df['amount_est'] = df['amount']
        df['data_source'] = f'akshare:{source_detail or "unknown"}'
        df['yahoo_code'] = normalize_a_share_code(code)
        spot_row, spot_errors = self._get_akshare_xq_spot_row(xq_code)
        errors.extend(spot_errors)
        if spot_row:
            spot_date = pd.to_datetime(spot_row.get("date"), errors="coerce")
            start_ts = pd.to_datetime(start)
            end_ts = pd.to_datetime(end)
            if not pd.isna(spot_date) and start_ts <= spot_date <= end_ts:
                df = df[df["date"] != spot_date].copy()
                df = pd.concat([df, pd.DataFrame([spot_row])], ignore_index=True, sort=False)
                df = df.sort_values("date").reset_index(drop=True)
                df["pct_chg"] = pd.to_numeric(df.get("pct_chg"), errors="coerce")
                df["pct_chg"] = df["pct_chg"].fillna(df["close"].pct_change() * 100)
        if errors:
            df.attrs['fallback_warning'] = "；".join(
                f"{e.get('interface', 'akshare')}失败:{e.get('message', '')}" for e in errors[-3:]
            )
        if use_cache:
            df.to_csv(cache_path, index=False, encoding='utf-8-sig')
        return df

    def _get_akshare_xq_spot_row(self, xq_code: str) -> tuple[dict | None, list[dict]]:
        raw, errors = safe_fetch(
            "akshare",
            "stock_individual_spot_xq",
            lambda: ak.stock_individual_spot_xq(symbol=xq_code, timeout=self.timeout),
            retries=1,
            min_interval=0.8,
            cache=self.file_cache,
        )
        if raw is None or raw.empty:
            return None, errors
        try:
            data = dict(zip(raw.iloc[:, 0].astype(str), raw.iloc[:, 1]))
            dt = pd.to_datetime(data.get("时间"), errors="coerce")
            if pd.isna(dt):
                return None, errors
            row = {
                "date": dt.normalize(),
                "open": data.get("今开"),
                "high": data.get("最高"),
                "low": data.get("最低"),
                "close": data.get("现价"),
                "volume": data.get("成交量"),
                "amount": data.get("成交额"),
                "turnover_rate": data.get("周转率"),
                "pct_chg": data.get("涨幅"),
                "data_source": "akshare:stock_individual_spot_xq",
                "yahoo_code": normalize_a_share_code(xq_code[-6:]),
            }
            for col in ["open", "high", "low", "close", "volume", "amount", "turnover_rate", "pct_chg"]:
                row[col] = pd.to_numeric(row[col], errors="coerce")
            row["amount_est"] = row["amount"]
            if pd.isna(row["close"]):
                return None, errors
            return row, errors
        except Exception as exc:
            return None, errors + [{"source": "akshare", "interface": "stock_individual_spot_xq", "error_type": exc.__class__.__name__, "message": str(exc), "fallback_used": "daily_only"}]

    def _get_sina_spot_row(self, code: str) -> tuple[dict | None, list[dict]]:
        ticker = display_code(normalize_a_share_code(code))
        market = 'sh' if ticker.startswith(('5', '6', '9')) else 'sz'
        if code.endswith('.HK'):
            market, ticker = 'hk', ticker
        
        url = f"http://hq.sinajs.cn/list={market}{ticker}"
        try:
            req = urllib.request.Request(url, headers={'Referer': 'http://finance.sina.com.cn'})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                text = resp.read().decode('gbk')
            
            match = re.search(r'="([^"]+)"', text)
            if not match:
                return None, [{"source": "sina", "interface": "spot", "error_type": "ValueError", "message": "Sina API returned empty"}]
            fields = match.group(1).split(',')
            
            # HK stocks have a different format in Sina (less fields), handle A-shares mainly
            if len(fields) < 32 and not code.endswith('.HK'):
                return None, [{"source": "sina", "interface": "spot", "error_type": "ValueError", "message": "Sina API returned invalid format"}]
                
            close_price = float(fields[3])
            if close_price <= 0:
                return None, [{"source": "sina", "interface": "spot", "error_type": "ValueError", "message": "Market closed or invalid price"}]
                
            prev_close = float(fields[2])
            pct_chg = (close_price - prev_close) / prev_close * 100 if prev_close > 0 else 0
            
            row = {
                "date": pd.to_datetime(fields[30]).normalize(),
                "open": float(fields[1]),
                "high": float(fields[4]),
                "low": float(fields[5]),
                "close": close_price,
                "volume": float(fields[8]), # Shares
                "amount": float(fields[9]),
                "turnover_rate": None,
                "pct_chg": pct_chg,
                "amount_est": float(fields[9]),
                "data_source": "sina:spot",
                "yahoo_code": normalize_a_share_code(code),
                "quote_updated_at": f"{fields[30]} {fields[31]}",
                "realtime_price": True,
            }
            return row, []
        except Exception as exc:
            return None, [{"source": "sina", "interface": "spot", "error_type": exc.__class__.__name__, "message": str(exc)}]


    def _with_realtime_quote(self, df: pd.DataFrame, code: str, end: str) -> pd.DataFrame:
        realtime_row, errors = self._get_efinance_realtime_row(code)
        
        # Fallback to direct Sina API if efinance fails or is not installed
        if not realtime_row:
            sina_row, sina_errors = self._get_sina_spot_row(code)
            errors.extend(sina_errors)
            if sina_row:
                realtime_row = sina_row

        if not realtime_row:
            if self.require_realtime:
                detail = "；".join(f"{e.get('interface', 'realtime')}失败:{e.get('message', '')}" for e in errors[-3:])
                raise RuntimeError(f"实时行情不可用，已拒绝使用旧收盘价：{detail or '接口返回空数据'}")
            return df

        quote_date = pd.to_datetime(realtime_row.get("date"), errors="coerce")
        end_ts = pd.to_datetime(end)
        latest_hist_date = pd.to_datetime(df["date"].max(), errors="coerce") if "date" in df and not df.empty else pd.NaT
        if pd.isna(quote_date) or quote_date > end_ts:
            if self.require_realtime:
                raise RuntimeError(f"实时行情日期不可用或超出查询区间：{realtime_row.get('date')}")
            return df
        if not pd.isna(latest_hist_date) and quote_date < latest_hist_date:
            if self.require_realtime:
                raise RuntimeError(
                    f"实时行情已过期，最新实时交易日 {quote_date.strftime('%Y-%m-%d')} 早于日线交易日 {latest_hist_date.strftime('%Y-%m-%d')}"
                )
            return df

        out = df[df["date"] != quote_date].copy()
        out = pd.concat([out, pd.DataFrame([realtime_row])], ignore_index=True, sort=False)
        out = out.sort_values("date").reset_index(drop=True)
        out.attrs.update(df.attrs)
        out.attrs["realtime_quote"] = True
        out.attrs["realtime_updated_at"] = realtime_row.get("quote_updated_at")
        out.attrs["realtime_source"] = realtime_row.get("data_source")
        return out

    def _get_efinance_realtime_row(self, code: str) -> tuple[dict | None, list[dict]]:
        if ef is None:
            return None, [{"source": "efinance", "interface": "get_latest_quote", "error_type": "ImportError", "message": "efinance 未安装"}]
        ticker = display_code(normalize_a_share_code(code))
        raw, errors = safe_fetch(
            "efinance",
            "get_latest_quote",
            lambda: ef.stock.get_latest_quote(ticker),
            retries=2,
            min_interval=0.8,
            cache=self.file_cache,
        )
        if raw is None or raw.empty:
            return None, errors
        try:
            row = raw.iloc[0].to_dict()
            quote_dt = pd.to_datetime(row.get("更新时间"), errors="coerce")
            trade_date = pd.to_datetime(row.get("最新交易日"), errors="coerce")
            if pd.isna(trade_date) and not pd.isna(quote_dt):
                trade_date = quote_dt.normalize()
            close = pd.to_numeric(row.get("最新价"), errors="coerce")
            if pd.isna(trade_date) or pd.isna(close) or float(close) <= 0:
                return None, errors + [{"source": "efinance", "interface": "get_latest_quote", "error_type": "ValueError", "message": "实时行情缺少有效日期或最新价"}]

            volume_hands = pd.to_numeric(row.get("成交量"), errors="coerce")
            amount = pd.to_numeric(row.get("成交额"), errors="coerce")
            realtime = {
                "date": trade_date.normalize(),
                "open": row.get("今开"),
                "high": row.get("最高"),
                "low": row.get("最低"),
                "close": close,
                "volume": volume_hands * 100 if not pd.isna(volume_hands) else None,
                "amount": amount,
                "turnover_rate": row.get("换手率"),
                "pct_chg": pd.to_numeric(row.get("涨跌幅"), errors="coerce"),
                "amount_est": amount,
                "data_source": "efinance:get_latest_quote",
                "yahoo_code": normalize_a_share_code(code),
                "quote_updated_at": quote_dt.strftime("%Y-%m-%d %H:%M:%S") if not pd.isna(quote_dt) else "",
                "realtime_price": True,
            }
            for col in ["open", "high", "low", "close", "volume", "amount", "turnover_rate", "pct_chg", "amount_est"]:
                realtime[col] = pd.to_numeric(realtime[col], errors="coerce")
            missing = [col for col in ["open", "high", "low", "close", "volume", "amount"] if pd.isna(realtime.get(col))]
            if missing:
                return None, errors + [{"source": "efinance", "interface": "get_latest_quote", "error_type": "ValueError", "message": f"实时行情字段缺失：{','.join(missing)}"}]
            return realtime, errors
        except Exception as exc:
            return None, errors + [{"source": "efinance", "interface": "get_latest_quote", "error_type": exc.__class__.__name__, "message": str(exc)}]

    def _get_hist_yfinance(self, code: str, start: str, end: str, use_cache: bool = True) -> pd.DataFrame:
        yahoo_code = normalize_a_share_code(code)
        cache_path = self._cache_path('yfinance', yahoo_code, start, end)
        if use_cache:
            cached = self._read_price_cache('yfinance', yahoo_code, start, end, ttl_seconds=3600)
            if cached is not None:
                return cached

        raw, errors = safe_fetch(
            "yfinance",
            "download",
            lambda: yf.download(
                yahoo_code,
                start=start,
                end=end,
                progress=False,
                auto_adjust=False,
                threads=False,
            ),
            retries=2,
            min_interval=0.8,
            cache=self.file_cache,
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

    def _get_hist_efinance(self, code: str, start: str, end: str, use_cache: bool = True) -> pd.DataFrame:
        if ef is None:
            raise RuntimeError('未安装 efinance')
        ticker = display_code(normalize_a_share_code(code))
        cache_path = self._cache_path('efinance', ticker, start, end)
        if use_cache:
            cached = self._read_price_cache('efinance', ticker, start, end, ttl_seconds=1800)
            if cached is not None:
                return cached

        fqt = 1 if self.adjust == 'qfq' else 2 if self.adjust == 'hfq' else 0
        raw, errors = safe_fetch(
            "efinance",
            "get_quote_history",
            lambda: ef.stock.get_quote_history(
                ticker,
                beg=self._to_yyyymmdd(start),
                end=self._to_yyyymmdd(end),
                klt=101,
                fqt=fqt,
            ),
            retries=1,
            min_interval=0.8,
            cache=self.file_cache,
        )
        if raw is None or raw.empty:
            raise ValueError(f'efinance没有获取到行情数据：{ticker}')

        col_map = {
            '日期': 'date', '开盘': 'open', '最高': 'high', '最低': 'low', '收盘': 'close',
            '成交量': 'volume', '成交额': 'amount', '涨跌幅': 'pct_chg', '换手率': 'turnover_rate',
        }
        df = raw.rename(columns=col_map).copy()
        keep = [c for c in ['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg', 'turnover_rate'] if c in df.columns]
        df = df[keep]
        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        for c in ['open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg', 'turnover_rate']:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors='coerce')
        df = df.dropna(subset=['date', 'close']).sort_values('date')
        if df.empty:
            raise ValueError(f'efinance没有获取到指定区间行情数据：{ticker}')
        if 'amount' not in df.columns:
            df['amount'] = df['close'] * df.get('volume', 0)
        if 'pct_chg' not in df.columns:
            df['pct_chg'] = df['close'].pct_change() * 100
        df['amount_est'] = df['amount']
        df['data_source'] = 'efinance'
        df['yahoo_code'] = normalize_a_share_code(code)
        if use_cache:
            df.to_csv(cache_path, index=False, encoding='utf-8-sig')
        return df
