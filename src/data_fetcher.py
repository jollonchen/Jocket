from __future__ import annotations

from pathlib import Path
from datetime import datetime
import json
import os
import re
import signal
import threading
import urllib.request
import urllib3
import requests
import pandas as pd
import yfinance as yf

from .cache_utils import FileCache, safe_fetch
from .utils import normalize_a_share_code, display_code, ensure_dirs
from .universe import DEFAULT_UNIVERSE

# Some macOS/Python environments fail on Eastmoney SSL through AkShare, and
# local proxy tools can break Chinese quote endpoints. Keep bypass helpers
# scoped to market-data calls instead of patching global requests behavior.
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
    if os.getenv("JOCKET_DISABLE_PROCESS_PROXIES", "").lower() not in {"1", "true", "yes"}:
        return
    for key in _PROXY_ENV_KEYS:
        os.environ.pop(key, None)
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"


_disable_process_proxies()

def _market_request_kwargs(**kwargs):
    kwargs.setdefault("verify", False)
    kwargs.setdefault("proxies", {"http": None, "https": None, "all": None})
    return kwargs

try:
    import akshare as ak
except Exception:  # pragma: no cover
    ak = None

try:
    import efinance as ef
except Exception:  # pragma: no cover
    ef = None

try:
    import baostock as bs
except Exception:  # pragma: no cover
    bs = None


class DataFetcher:
    """Market data fetcher with selectable providers.

    provider:
    - auto: try direct public A-share feeds, AkShare, efinance, Tonghuashun and yfinance fallback
    - baidu: Baidu Gushitong K-line with MA fields
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
        if provider == 'baidu':
            return self._with_realtime_quote(self._get_hist_baidu(code, start, end, use_cache), code, end)
        if provider == 'baostock':
            return self._with_realtime_quote(self._get_hist_baostock(code, start, end, use_cache), code, end)

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
        if not is_hk and self._is_a_share(code):
            try:
                return self._with_realtime_quote(self._get_hist_baidu(code, start, end, use_cache), code, end)
            except Exception as exc:
                errors.append(f'百度股市通失败：{exc}')

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

        if not is_hk and self._is_a_share(code):
            try:
                df = self._get_hist_baostock(code, start, end, use_cache)
                return self._with_realtime_quote(df, code, end)
            except Exception as exc:
                errors.append(f'BaoStock失败：{exc}')
            
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
    def _is_a_share(code: str) -> bool:
        ycode = normalize_a_share_code(code)
        return ycode.endswith((".SS", ".SZ"))

    @staticmethod
    def _num(value):
        try:
            if value is None or pd.isna(value):
                return None
            if isinstance(value, str):
                value = value.strip().replace("%", "").replace(",", "")
                if not value or value in {"-", "--", "None", "nan"}:
                    return None
            return float(value)
        except Exception:
            return None

    @staticmethod
    def _source_error(source: str, interface: str, message: str, error_type: str = "ValueError") -> dict:
        return {"source": source, "interface": interface, "error_type": error_type, "message": str(message)}

    @staticmethod
    def _first_value(mapping: dict, names: list[str]):
        lowered = {str(k).strip().lower(): v for k, v in mapping.items()}
        for name in names:
            if name in mapping:
                return mapping[name]
            value = lowered.get(str(name).strip().lower())
            if value is not None:
                return value
        return None

    def _call_with_timeout(self, func, seconds: float | None = None):
        seconds = max(3, int(seconds or self.timeout or 8))
        if threading.current_thread() is not threading.main_thread():
            return func()

        def _timeout_handler(signum, frame):
            raise TimeoutError(f"接口超过 {seconds} 秒未返回")

        previous_handler = signal.getsignal(signal.SIGALRM)
        previous_timer = signal.setitimer(signal.ITIMER_REAL, seconds)
        signal.signal(signal.SIGALRM, _timeout_handler)
        try:
            return func()
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)
            if previous_timer and previous_timer[0] > 0:
                signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])

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
                'User-Agent': 'Mozilla/5.0 (Jocket)',
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

    def _get_hist_baidu(self, code: str, start: str, end: str, use_cache: bool = True) -> pd.DataFrame:
        ticker = display_code(normalize_a_share_code(code))
        cache_path = self._cache_path('baidu', ticker, start, end)
        if use_cache:
            cached = self._read_price_cache('baidu', ticker, start, end, ttl_seconds=1800)
            if cached is not None:
                return cached

        def fetch():
            url = "https://finance.pae.baidu.com/selfselect/getstockquotation"
            params = {
                "all": "1",
                "isIndex": "false",
                "isBk": "false",
                "isBlock": "false",
                "isFutures": "false",
                "isStock": "true",
                "newFormat": "1",
                "group": "quotation_kline_ab",
                "finClientType": "pc",
                "code": ticker,
                "ktype": "1",
            }
            headers = {
                "User-Agent": "Mozilla/5.0 Jocket",
                "Accept": "application/vnd.finance-web.v1+json",
                "Origin": "https://gushitong.baidu.com",
                "Referer": "https://gushitong.baidu.com/",
            }
            response = requests.get(url, params=params, headers=headers, timeout=self.timeout, **_market_request_kwargs())
            response.raise_for_status()
            return response.json()

        payload, errors = safe_fetch("baidu", "getstockquotation_kline", fetch, retries=1, min_interval=0.8, cache=self.file_cache)
        if payload is None:
            raise RuntimeError("百度股市通 K 线接口暂不可用：" + "；".join(str(e.get("message", e)) for e in errors[-2:]))
        md = ((payload.get("Result") or {}).get("newMarketData") or {})
        keys = md.get("keys") or []
        rows = []
        for raw in str(md.get("marketData") or "").split(";"):
            vals = raw.split(",")
            if len(vals) != len(keys):
                continue
            rows.append(dict(zip(keys, vals)))
        if not rows:
            raise ValueError(f"百度股市通没有获取到行情数据：{ticker}")
        df = pd.DataFrame(rows).rename(
            columns={
                "time": "date",
                "volume": "volume",
                "amount": "amount",
                "ma5avgprice": "ma5_baidu",
                "ma10avgprice": "ma10_baidu",
                "ma20avgprice": "ma20_baidu",
            }
        )
        for col in ["date", "open", "high", "low", "close", "volume", "amount", "ma5_baidu", "ma10_baidu", "ma20_baidu"]:
            if col not in df.columns:
                continue
            if col == "date":
                df[col] = pd.to_datetime(df[col], errors="coerce")
            else:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["date", "close"]).sort_values("date")
        start_ts = pd.to_datetime(start)
        end_ts = pd.to_datetime(end)
        df = df[(df["date"] >= start_ts) & (df["date"] <= end_ts)]
        if df.empty:
            raise ValueError(f"百度股市通没有获取到指定区间行情数据：{ticker}")
        if "amount" not in df.columns:
            df["amount"] = df["close"] * df.get("volume", 0)
        df["pct_chg"] = df["close"].pct_change() * 100
        df["amount_est"] = df["amount"]
        df["data_source"] = "baidu:gushitong_kline"
        df["yahoo_code"] = normalize_a_share_code(code)
        if use_cache:
            df.to_csv(cache_path, index=False, encoding="utf-8-sig")
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
                    lambda: self._call_with_timeout(
                        lambda: ak.stock_hk_hist(
                            symbol=ak_code,
                            start_date=self._to_yyyymmdd(start),
                            end_date=self._to_yyyymmdd(end),
                            adjust=self.adjust,
                            timeout=self.timeout,
                        )
                    ),
                )
            )
        else:
            ak_attempts = [
                (
                    "stock_zh_a_hist_em",
                    lambda: self._call_with_timeout(
                        lambda: ak.stock_zh_a_hist(
                            symbol=ak_code,
                            period='daily',
                            start_date=self._to_yyyymmdd(start),
                            end_date=self._to_yyyymmdd(end),
                            adjust=self.adjust,
                            timeout=self.timeout,
                        )
                    ),
                ),
                (
                    "stock_zh_a_daily_sina",
                    lambda: self._call_with_timeout(
                        lambda: ak.stock_zh_a_daily(
                            symbol=prefixed_code,
                            start_date=self._to_yyyymmdd(start),
                            end_date=self._to_yyyymmdd(end),
                            adjust=self.adjust,
                        )
                    ),
                ),
                (
                    "stock_zh_a_hist_tx",
                    lambda: self._call_with_timeout(
                        lambda: ak.stock_zh_a_hist_tx(
                            symbol=prefixed_code,
                            start_date=self._to_yyyymmdd(start),
                            end_date=self._to_yyyymmdd(end),
                            adjust=self.adjust,
                            timeout=self.timeout,
                        )
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
        if errors:
            df.attrs['fallback_warning'] = "；".join(
                f"{e.get('interface', 'akshare')}失败:{e.get('message', '')}" for e in errors[-3:]
            )
        if use_cache:
            df.to_csv(cache_path, index=False, encoding='utf-8-sig')
        return df

    def _get_akshare_xq_spot_row(self, xq_code: str) -> tuple[dict | None, list[dict]]:
        if ak is None:
            return None, [self._source_error("akshare", "stock_individual_spot_xq", "AkShare 未安装", "ImportError")]
        raw, errors = safe_fetch(
            "akshare",
            "stock_individual_spot_xq",
            lambda: self._call_with_timeout(lambda: ak.stock_individual_spot_xq(symbol=xq_code, timeout=self.timeout)),
            retries=0,
            min_interval=0.8,
            cache=self.file_cache,
        )
        if raw is None:
            return None, errors
        try:
            if isinstance(raw, pd.DataFrame):
                if raw.empty:
                    return None, errors + [self._source_error("akshare", "stock_individual_spot_xq", "AkShare 雪球实时接口返回空表")]
                if raw.shape[1] >= 2 and set(raw.columns[:2]) != {"date", "close"}:
                    data = dict(zip(raw.iloc[:, 0].astype(str), raw.iloc[:, 1]))
                else:
                    data = raw.iloc[0].to_dict()
            elif isinstance(raw, dict):
                data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
            else:
                return None, errors + [self._source_error("akshare", "stock_individual_spot_xq", f"不支持的返回类型：{type(raw).__name__}")]

            dt = pd.to_datetime(self._first_value(data, ["时间", "timestamp", "time", "日期", "date"]), errors="coerce")
            close = self._num(self._first_value(data, ["现价", "当前价", "最新", "最新价", "current", "price", "close"]))
            prev_close = self._num(self._first_value(data, ["昨收", "昨收价", "prev_close", "previous_close"]))
            pct_chg = self._num(self._first_value(data, ["涨幅", "涨跌幅", "percent", "pct_chg"]))
            if pct_chg is not None and abs(pct_chg) > 1:
                pct_chg = pct_chg
            if pct_chg is None and close is not None and prev_close:
                pct_chg = (close - prev_close) / prev_close * 100
            row = {
                "date": dt.normalize() if not pd.isna(dt) else pd.NaT,
                "open": self._first_value(data, ["今开", "开盘", "open"]),
                "high": self._first_value(data, ["最高", "最高价", "high"]),
                "low": self._first_value(data, ["最低", "最低价", "low"]),
                "close": close,
                "volume": self._first_value(data, ["成交量", "volume", "vol"]),
                "amount": self._first_value(data, ["成交额", "amount"]),
                "turnover_rate": self._first_value(data, ["周转率", "换手率", "turnover_rate"]),
                "pct_chg": pct_chg,
                "data_source": "akshare:stock_individual_spot_xq",
                "yahoo_code": normalize_a_share_code(xq_code[-6:]),
                "quote_updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "realtime_price": True,
            }
            for col in ["open", "high", "low", "close", "volume", "amount", "turnover_rate", "pct_chg"]:
                row[col] = pd.to_numeric(row[col], errors="coerce")
            row["amount_est"] = row["amount"]
            missing = self._missing_realtime_fields(row, require_date=False)
            if missing:
                return None, errors + [self._source_error("akshare", "stock_individual_spot_xq", f"雪球实时字段缺失：{','.join(missing)}")]
            return row, errors
        except Exception as exc:
            return None, errors + [self._source_error("akshare", "stock_individual_spot_xq", str(exc), exc.__class__.__name__)]

    def _get_akshare_bid_ask_row(self, code: str) -> tuple[dict | None, list[dict]]:
        if ak is None:
            return None, [self._source_error("akshare", "stock_bid_ask_em", "AkShare 未安装", "ImportError")]
        ticker = display_code(normalize_a_share_code(code))
        raw, errors = safe_fetch(
            "akshare",
            "stock_bid_ask_em",
            lambda: self._call_with_timeout(lambda: ak.stock_bid_ask_em(symbol=ticker)),
            retries=0,
            min_interval=0.8,
            cache=self.file_cache,
        )
        if raw is None:
            return None, errors
        try:
            if raw.empty or raw.shape[1] < 2:
                return None, errors + [self._source_error("akshare", "stock_bid_ask_em", "东财盘口实时接口返回空表")]
            data = dict(zip(raw.iloc[:, 0].astype(str), raw.iloc[:, 1]))
            close = self._num(data.get("最新"))
            prev_close = self._num(data.get("昨收"))
            pct_chg = self._num(data.get("涨幅"))
            if pct_chg is None and close is not None and prev_close:
                pct_chg = (close - prev_close) / prev_close * 100
            volume_hands = self._num(data.get("总手"))
            amount_wan = self._num(data.get("金额"))
            amount = amount_wan * 10000 if amount_wan is not None and amount_wan < 100000000 else amount_wan
            row = {
                "date": pd.Timestamp.now(tz="Asia/Shanghai").tz_localize(None).normalize(),
                "open": data.get("今开"),
                "high": data.get("最高"),
                "low": data.get("最低"),
                "close": close,
                "volume": volume_hands * 100 if volume_hands is not None else None,
                "amount": amount,
                "turnover_rate": data.get("换手"),
                "pct_chg": pct_chg,
                "amount_est": amount,
                "data_source": "akshare:stock_bid_ask_em",
                "yahoo_code": normalize_a_share_code(code),
                "quote_updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "realtime_price": True,
                "date_inferred": True,
            }
            for col in ["open", "high", "low", "close", "volume", "amount", "turnover_rate", "pct_chg", "amount_est"]:
                row[col] = pd.to_numeric(row[col], errors="coerce")
            missing = self._missing_realtime_fields(row, require_date=False)
            if missing:
                return None, errors + [self._source_error("akshare", "stock_bid_ask_em", f"东财盘口字段缺失：{','.join(missing)}")]
            return row, errors
        except Exception as exc:
            return None, errors + [self._source_error("akshare", "stock_bid_ask_em", str(exc), exc.__class__.__name__)]

    def _get_sina_spot_row(self, code: str) -> tuple[dict | None, list[dict]]:
        ticker = display_code(normalize_a_share_code(code))
        market = 'sh' if ticker.startswith(('5', '6', '9')) else 'sz'
        url = f"http://hq.sinajs.cn/list={market}{ticker}"
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 Jocket",
                    "Referer": "http://finance.sina.com.cn",
                },
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                text = resp.read().decode("gbk", errors="ignore")
            match = re.search(r'="([^"]*)"', text)
            if not match:
                return None, [self._source_error("sina", "hq_sinajs", "新浪实时接口返回空内容")]
            fields = match.group(1).split(",")
            if len(fields) < 32:
                return None, [self._source_error("sina", "hq_sinajs", f"新浪实时字段不足：{len(fields)}")]
            close = self._num(fields[3])
            prev_close = self._num(fields[2])
            amount = self._num(fields[9])
            row = {
                "date": pd.to_datetime(fields[30], errors="coerce").normalize(),
                "open": fields[1],
                "high": fields[4],
                "low": fields[5],
                "close": close,
                "volume": fields[8],
                "amount": amount,
                "turnover_rate": None,
                "pct_chg": (close - prev_close) / prev_close * 100 if close is not None and prev_close else None,
                "amount_est": amount,
                "data_source": "sina:hq_sinajs",
                "yahoo_code": normalize_a_share_code(code),
                "quote_updated_at": f"{fields[30]} {fields[31]}",
                "realtime_price": True,
            }
            for col in ["open", "high", "low", "close", "volume", "amount", "pct_chg", "amount_est"]:
                row[col] = pd.to_numeric(row[col], errors="coerce")
            missing = self._missing_realtime_fields(row)
            if missing:
                return None, [self._source_error("sina", "hq_sinajs", f"新浪实时字段缺失：{','.join(missing)}")]
            return row, []
        except Exception as exc:
            return None, [self._source_error("sina", "hq_sinajs", str(exc), exc.__class__.__name__)]

    def _get_tencent_spot_row(self, code: str) -> tuple[dict | None, list[dict]]:
        ticker = display_code(normalize_a_share_code(code))
        market = 'sh' if ticker.startswith(('5', '6', '9')) else 'sz'
        url = f"https://qt.gtimg.cn/q={market}{ticker}"
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 Jocket",
                    "Referer": "https://finance.qq.com/",
                },
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                text = resp.read().decode("gbk", errors="ignore")
            match = re.search(r'="([^"]*)"', text)
            if not match:
                return None, [self._source_error("tencent", "qt_gtimg", "腾讯实时接口返回空内容")]
            fields = match.group(1).split("~")
            if len(fields) < 38:
                return None, [self._source_error("tencent", "qt_gtimg", f"腾讯实时字段不足：{len(fields)}")]
            close = self._num(fields[3])
            prev_close = self._num(fields[4])
            quote_dt = pd.to_datetime(fields[30], format="%Y%m%d%H%M%S", errors="coerce")
            amount_wan = self._num(fields[37])
            amount = amount_wan * 10000 if amount_wan is not None else None
            volume_hands = self._num(fields[36])
            row = {
                "date": quote_dt.normalize() if not pd.isna(quote_dt) else pd.NaT,
                "open": fields[5],
                "high": fields[33],
                "low": fields[34],
                "close": close,
                "volume": volume_hands * 100 if volume_hands is not None else None,
                "amount": amount,
                "turnover_rate": fields[38] if len(fields) > 38 else None,
                "pct_chg": self._num(fields[32]) if len(fields) > 32 else ((close - prev_close) / prev_close * 100 if close is not None and prev_close else None),
                "amount_est": amount,
                "data_source": "tencent:qt_gtimg",
                "yahoo_code": normalize_a_share_code(code),
                "quote_updated_at": quote_dt.strftime("%Y-%m-%d %H:%M:%S") if not pd.isna(quote_dt) else "",
                "realtime_price": True,
            }
            for col in ["open", "high", "low", "close", "volume", "amount", "turnover_rate", "pct_chg", "amount_est"]:
                row[col] = pd.to_numeric(row[col], errors="coerce")
            missing = self._missing_realtime_fields(row)
            if missing:
                return None, [self._source_error("tencent", "qt_gtimg", f"腾讯实时字段缺失：{','.join(missing)}")]
            return row, []
        except Exception as exc:
            return None, [self._source_error("tencent", "qt_gtimg", str(exc), exc.__class__.__name__)]

    @staticmethod
    def _missing_realtime_fields(row: dict, require_date: bool = True) -> list[str]:
        required = ["open", "high", "low", "close", "volume", "amount"]
        if require_date:
            required.insert(0, "date")
        missing = []
        for field in required:
            value = row.get(field)
            if field == "date":
                if pd.isna(pd.to_datetime(value, errors="coerce")):
                    missing.append(field)
                continue
            if pd.isna(pd.to_numeric(value, errors="coerce")):
                missing.append(field)
        return missing

    def _with_realtime_quote(self, df: pd.DataFrame, code: str, end: str) -> pd.DataFrame:
        realtime_row = None
        errors = []

        realtime_attempts = [
            ("AkShare雪球实时", lambda: self._get_akshare_xq_spot_row(self._to_xq_code(code))),
            ("AkShare东财盘口", lambda: self._get_akshare_bid_ask_row(code)),
            ("efinance实时", lambda: self._get_efinance_realtime_row(code)),
            ("新浪实时", lambda: self._get_sina_spot_row(code)),
            ("腾讯实时", lambda: self._get_tencent_spot_row(code)),
        ]
        for _, fetcher in realtime_attempts:
            row, row_errors = fetcher()
            errors.extend(row_errors)
            if row:
                realtime_row = row
                break

        if not realtime_row:
            try:
                yf_hist = self._get_hist_yfinance(
                    code,
                    start=(datetime.now() - pd.Timedelta(days=10)).strftime('%Y-%m-%d'),
                    end=(pd.Timestamp(end) + pd.Timedelta(days=1)).strftime('%Y-%m-%d'),
                    use_cache=False,
                )
                if not yf_hist.empty:
                    last_row = yf_hist.iloc[-1].to_dict()
                    amount = last_row.get("amount") or last_row.get("amount_est")
                    last_row.update({
                        "amount": amount,
                        "amount_est": amount,
                        "data_source": "yfinance:recent_quote",
                        "quote_updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "realtime_price": True,
                    })
                    missing = self._missing_realtime_fields(last_row)
                    if missing:
                        errors.append(self._source_error("yfinance", "recent_quote", f"最近行情字段缺失：{','.join(missing)}"))
                    else:
                        realtime_row = last_row
            except Exception as e:
                errors.append(self._source_error("yfinance", "recent_quote", str(e), e.__class__.__name__))

        if not realtime_row:
            if self.require_realtime:
                detail = "；".join(f"{e.get('source', 'source')}.{e.get('interface', 'realtime')}失败:{e.get('message', '')}" for e in errors[-8:])
                raise RuntimeError(f"实时行情不可用，已拒绝使用旧收盘价：{detail or '接口返回空数据'}")
            return df

        quote_date = pd.to_datetime(realtime_row.get("date"), errors="coerce")
        end_ts = pd.to_datetime(end)
        latest_hist_date = pd.to_datetime(df["date"].max(), errors="coerce") if "date" in df and not df.empty else pd.NaT
        if bool(realtime_row.get("date_inferred")) and not pd.isna(latest_hist_date):
            quote_date = latest_hist_date
            realtime_row["date"] = quote_date
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
        missing = self._missing_realtime_fields(realtime_row)
        if missing:
            if self.require_realtime:
                raise RuntimeError(f"实时行情字段不完整，缺少：{','.join(missing)}；来源：{realtime_row.get('data_source', '-')}")
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

    def _get_hist_baostock(self, code: str, start: str, end: str, use_cache: bool = True) -> pd.DataFrame:
        if bs is None:
            raise RuntimeError("未安装 baostock，请先执行：pip install baostock")
        ticker = display_code(normalize_a_share_code(code))
        cache_path = self._cache_path("baostock", ticker, start, end)
        if use_cache:
            cached = self._read_price_cache("baostock", ticker, start, end, ttl_seconds=3600)
            if cached is not None:
                return cached

        market = "sh" if ticker.startswith(("5", "6", "9")) else "sz"
        adjustflag = "2" if self.adjust == "qfq" else "1" if self.adjust == "hfq" else "3"
        login = bs.login()
        if getattr(login, "error_code", "0") != "0":
            raise RuntimeError(f"baostock登录失败：{getattr(login, 'error_msg', '')}")
        try:
            rs = bs.query_history_k_data_plus(
                f"{market}.{ticker}",
                "date,open,high,low,close,volume,amount,pctChg,turn",
                start_date=start,
                end_date=end,
                frequency="d",
                adjustflag=adjustflag,
            )
            rows = []
            while rs.error_code == "0" and rs.next():
                rows.append(rs.get_row_data())
            if rs.error_code != "0":
                raise RuntimeError(rs.error_msg)
        finally:
            bs.logout()
        if not rows:
            raise ValueError(f"baostock没有获取到行情数据：{ticker}")

        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume", "amount", "pct_chg", "turnover_rate"])
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        for col in ["open", "high", "low", "close", "volume", "amount", "pct_chg", "turnover_rate"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["date", "close"]).sort_values("date")
        if df.empty:
            raise ValueError(f"baostock没有获取到指定区间行情数据：{ticker}")
        if "amount" not in df.columns:
            df["amount"] = df["close"] * df.get("volume", 0)
        if "pct_chg" not in df.columns:
            df["pct_chg"] = df["close"].pct_change() * 100
        df["amount_est"] = df["amount"]
        df["data_source"] = "baostock"
        df["yahoo_code"] = normalize_a_share_code(code)
        if use_cache:
            df.to_csv(cache_path, index=False, encoding="utf-8-sig")
        return df
