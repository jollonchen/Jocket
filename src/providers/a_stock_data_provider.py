from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from .base_provider import BaseProvider, ProviderResult
from ..cache_utils import FileCache, safe_fetch
from ..utils import display_code, normalize_a_share_code


UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"


def _code6(code: str) -> str:
    return display_code(normalize_a_share_code(str(code or "").strip()))


def _prefix(code: str) -> str:
    ticker = _code6(code)
    if ticker.startswith(("6", "9", "5")):
        return "sh"
    if ticker.startswith("8"):
        return "bj"
    return "sz"


def _secid(code: str) -> str:
    ticker = _code6(code)
    return ("1." if _prefix(ticker) == "sh" else "0.") + ticker


def _num(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        if isinstance(value, str):
            value = value.strip().replace(",", "").replace("%", "")
            if value in {"", "-", "--", "None", "nan"}:
                return None
        return float(value)
    except Exception:
        return None


def _jsonp_payload(text: str) -> dict:
    text = str(text or "").strip()
    match = re.search(r"\((\{.*\})\)\s*;?$", text, re.S)
    if match:
        text = match.group(1)
    return json.loads(text)


def _parse_any_date(value: Any) -> str | None:
    if value is None or value == "":
        return None
    dt = pd.to_datetime(value, errors="coerce")
    if pd.isna(dt):
        return None
    return dt.strftime("%Y-%m-%d")


def _request_json(url: str, params: dict | None = None, *, headers: dict | None = None, timeout: float = 12) -> dict:
    response = requests.get(url, params=params, headers=headers or {"User-Agent": UA}, timeout=timeout)
    response.raise_for_status()
    text = response.text.strip()
    if text.startswith(("callback", "jQuery", "datatable")) or re.match(r"^[\w$]+\(", text):
        return _jsonp_payload(text)
    return response.json()


class AStockDataProvider(BaseProvider):
    """Direct A-share public-data provider inspired by simonlin1212/a-stock-data V3.1.

    It intentionally returns normalized, small payloads for the app rather than
    exposing every raw field to Streamlit. Raw rows are still preserved inside
    endpoint payloads for diagnostics and AI context.
    """

    name = "a_stock_data"

    def __init__(self, cache: FileCache | None = None, config: dict | None = None):
        self.cache = cache or FileCache("data/cache")
        self.config = config or {}
        cfg = (self.config.get("a_stock_data") or {}) if isinstance(self.config, dict) else {}
        self.timeout = float(cfg.get("timeout", self.config.get("data", {}).get("timeout", 12) if isinstance(self.config, dict) else 12))
        self.ttl = int(cfg.get("ttl_seconds", 1800))
        self.detail_dir = Path("data/a_stock_data")
        self.detail_dir.mkdir(parents=True, exist_ok=True)

    def _cached(self, key: str, fetcher, *, ttl: int | None = None) -> ProviderResult:
        cached = self.cache.get_pickle("fundamentals", f"a_stock_{key}", ttl_seconds=ttl or self.ttl)
        if cached is not None:
            return ProviderResult(data=cached, source=self.name, from_cache=True)
        data, errors = safe_fetch(self.name, key, fetcher, retries=1, min_interval=0.4, cache=self.cache)
        if data is not None:
            self.cache.set_pickle("fundamentals", f"a_stock_{key}", data)
        return ProviderResult(data=data, source=self.name, warnings=errors)

    def tencent_quote(self, codes: list[str]) -> ProviderResult:
        def fetch():
            prefixed = [f"{_prefix(code)}{_code6(code)}" for code in codes]
            url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://finance.qq.com/"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                text = resp.read().decode("gbk", errors="ignore")
            out: dict[str, dict] = {}
            for line in text.strip().split(";"):
                if "=" not in line or '"' not in line:
                    continue
                key = line.split("=")[0].split("_")[-1]
                vals = line.split('"')[1].split("~")
                if len(vals) < 53:
                    continue
                code = key[2:]
                out[code] = {
                    "code": code,
                    "name": vals[1],
                    "price": _num(vals[3]),
                    "last_close": _num(vals[4]),
                    "open": _num(vals[5]),
                    "change_amt": _num(vals[31]),
                    "change_pct": _num(vals[32]),
                    "high": _num(vals[33]),
                    "low": _num(vals[34]),
                    "volume_hands": _num(vals[36]),
                    "amount_wan": _num(vals[37]),
                    "turnover_pct": _num(vals[38]),
                    "pe_ttm": _num(vals[39]),
                    "amplitude_pct": _num(vals[43]),
                    "market_cap_yi": _num(vals[44]),
                    "float_market_cap_yi": _num(vals[45]),
                    "pb": _num(vals[46]),
                    "limit_up": _num(vals[47]),
                    "limit_down": _num(vals[48]),
                    "vol_ratio": _num(vals[49]),
                    "pe_static": _num(vals[52]),
                    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            if not out:
                raise ValueError("腾讯行情返回空")
            return out

        return self._cached("tencent_quote_" + "_".join(_code6(c) for c in codes), fetch, ttl=300)

    def baidu_kline_with_ma(self, code: str) -> ProviderResult:
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
                "code": _code6(code),
                "ktype": "1",
            }
            headers = {
                "User-Agent": UA,
                "Accept": "application/vnd.finance-web.v1+json",
                "Origin": "https://gushitong.baidu.com",
                "Referer": "https://gushitong.baidu.com/",
            }
            d = _request_json(url, params, headers=headers, timeout=self.timeout)
            md = (d.get("Result") or {}).get("newMarketData") or {}
            keys = md.get("keys") or []
            rows = []
            for raw in str(md.get("marketData") or "").split(";"):
                vals = raw.split(",")
                if len(vals) != len(keys):
                    continue
                rows.append(dict(zip(keys, vals)))
            return {"keys": keys, "rows": rows[-120:], "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

        return self._cached(f"baidu_kline_{_code6(code)}", fetch, ttl=900)

    def eastmoney_reports(self, code: str, max_pages: int = 2) -> ProviderResult:
        def fetch():
            rows = []
            session = requests.Session()
            session.headers.update({"User-Agent": UA, "Referer": "https://data.eastmoney.com/"})
            for page in range(1, max_pages + 1):
                params = {
                    "industryCode": "*",
                    "pageSize": "50",
                    "industry": "*",
                    "rating": "*",
                    "ratingChange": "*",
                    "beginTime": "2000-01-01",
                    "endTime": "2030-01-01",
                    "pageNo": str(page),
                    "qType": "0",
                    "code": _code6(code),
                    "pageNumber": str(page),
                }
                r = session.get("https://reportapi.eastmoney.com/report/list", params=params, timeout=self.timeout)
                r.raise_for_status()
                data = r.json()
                batch = data.get("data") or []
                rows.extend(batch)
                if not batch or page >= int(data.get("TotalPage") or 1):
                    break
                time.sleep(0.2)
            return rows

        return self._cached(f"eastmoney_reports_{_code6(code)}", fetch, ttl=12 * 3600)

    def ths_eps_forecast(self, code: str) -> ProviderResult:
        def fetch():
            url = f"https://basic.10jqka.com.cn/new/{_code6(code)}/worth.html"
            r = requests.get(url, headers={"User-Agent": UA, "Referer": "https://basic.10jqka.com.cn/"}, timeout=self.timeout)
            r.encoding = "gbk"
            dfs = pd.read_html(StringIO(r.text))
            for df in dfs:
                text = " ".join(map(str, df.columns)) + " " + " ".join(map(str, df.head(2).values.flatten()))
                if "每股收益" in text or "均值" in text or "EPS" in text.upper():
                    return df
            return dfs[0] if dfs else pd.DataFrame()

        return self._cached(f"ths_eps_{_code6(code)}", fetch, ttl=24 * 3600)

    def ths_hot_reason(self, trade_date: str | None = None) -> ProviderResult:
        def fetch():
            date = pd.to_datetime(trade_date or datetime.now()).strftime("%Y-%m-%d")
            url = f"http://zx.10jqka.com.cn/event/api/getharden/date/{date}/orderby/date/orderway/desc/charset/GBK/"
            data = _request_json(url, headers={"User-Agent": UA}, timeout=self.timeout)
            if data.get("errocode", 0) != 0:
                raise RuntimeError(f"同花顺热点错误: {data.get('errormsg', '')}")
            rows = data.get("data") or data.get("result") or []
            if isinstance(rows, dict):
                rows = rows.get("list") or rows.get("stock_list") or []
            return self._normalize_hot_rows(rows)

        key_date = pd.to_datetime(trade_date or datetime.now()).strftime("%Y%m%d")
        return self._cached(f"ths_hot_reason_{key_date}", fetch, ttl=900)

    @staticmethod
    def _normalize_hot_rows(rows: list[dict]) -> pd.DataFrame:
        out = []
        for row in rows or []:
            code = row.get("code") or row.get("股票代码") or row.get("stock_code")
            name = row.get("name") or row.get("股票简称") or row.get("stock_name")
            reason = row.get("reason") or row.get("hot_reason") or row.get("concept_tag") or row.get("tag") or row.get("入选理由")
            out.append(
                {
                    "code": _code6(str(code or "")) if code else "",
                    "name": name or "",
                    "reason": reason or "",
                    "hot_rank": _num(row.get("rank") or row.get("排名")),
                    "heat": _num(row.get("heat") or row.get("热度") or row.get("score")),
                    "raw": row,
                }
            )
        return pd.DataFrame(out)

    def hsgt_realtime(self) -> ProviderResult:
        def fetch():
            url = "https://push2.eastmoney.com/api/qt/kamt/get"
            params = {"fields1": "f1,f2,f3,f4", "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63"}
            data = _request_json(url, params, timeout=self.timeout)
            return data.get("data") or data

        return self._cached("hsgt_realtime", fetch, ttl=300)

    def baidu_concept_blocks(self, code: str) -> ProviderResult:
        def fetch():
            url = "https://finance.pae.baidu.com/selfselect/getstockquotation"
            params = {
                "all": "1",
                "isIndex": "false",
                "isBk": "false",
                "isBlock": "false",
                "isStock": "true",
                "newFormat": "1",
                "group": "finance",
                "finClientType": "pc",
                "code": _code6(code),
            }
            d = _request_json(url, params, headers={"User-Agent": UA, "Referer": "https://gushitong.baidu.com/"}, timeout=self.timeout)
            result = d.get("Result") or {}
            blocks = result.get("concepts") or result.get("blocks") or result.get("plate") or []
            return {"blocks": blocks, "raw": result}

        return self._cached(f"baidu_concepts_{_code6(code)}", fetch, ttl=3600)

    def eastmoney_fund_flow_minute(self, code: str) -> ProviderResult:
        def fetch():
            url = "https://push2.eastmoney.com/api/qt/stock/fflow/daykline/get"
            params = {
                "lmt": "0",
                "klt": "1",
                "secid": _secid(code),
                "fields1": "f1,f2,f3,f7",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63",
            }
            data = _request_json(url, params, timeout=self.timeout)
            klines = ((data.get("data") or {}).get("klines")) or []
            return [self._parse_fund_flow_row(item) for item in klines[-120:]]

        return self._cached(f"em_fund_flow_minute_{_code6(code)}", fetch, ttl=600)

    @staticmethod
    def _parse_fund_flow_row(item: str) -> dict:
        parts = str(item).split(",")
        keys = [
            "time",
            "main_net_inflow",
            "small_net_inflow",
            "medium_net_inflow",
            "large_net_inflow",
            "super_large_net_inflow",
            "main_net_ratio",
            "small_net_ratio",
            "medium_net_ratio",
            "large_net_ratio",
            "super_large_net_ratio",
        ]
        row = dict(zip(keys, parts))
        for key in keys[1:]:
            row[key] = _num(row.get(key))
        return row

    def stock_fund_flow_120d(self, code: str) -> ProviderResult:
        def fetch():
            url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
            params = {
                "lmt": "120",
                "klt": "101",
                "secid": _secid(code),
                "fields1": "f1,f2,f3,f7",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63",
            }
            data = _request_json(url, params, timeout=self.timeout)
            klines = ((data.get("data") or {}).get("klines")) or []
            return [self._parse_fund_flow_row(item) for item in klines[-120:]]

        return self._cached(f"em_fund_flow_120d_{_code6(code)}", fetch, ttl=3600)

    def eastmoney_datacenter(self, report_name: str, *, filter_str: str = "", page_size: int = 50, sort_columns: str = "", sort_types: str = "-1") -> ProviderResult:
        def fetch():
            params = {
                "reportName": report_name,
                "columns": "ALL",
                "filter": filter_str,
                "pageNumber": "1",
                "pageSize": str(page_size),
                "sortColumns": sort_columns,
                "sortTypes": sort_types,
                "source": "WEB",
                "client": "WEB",
            }
            data = _request_json(DATACENTER_URL, params, timeout=self.timeout)
            return ((data.get("result") or {}).get("data")) or []

        key = f"datacenter_{report_name}_{filter_str}_{page_size}_{sort_columns}_{sort_types}"
        return self._cached(key, fetch, ttl=3600)

    def dragon_tiger_board(self, code: str, look_back: int = 30) -> ProviderResult:
        ticker = _code6(code)
        return self.eastmoney_datacenter(
            "RPT_DAILYBILLBOARD_DETAILS",
            filter_str=f'(SECURITY_CODE="{ticker}")',
            page_size=80,
            sort_columns="TRADE_DATE",
        )

    def daily_dragon_tiger(self, trade_date: str | None = None) -> ProviderResult:
        date = (pd.to_datetime(trade_date).strftime("%Y-%m-%d") if trade_date else datetime.now().strftime("%Y-%m-%d"))
        return self.eastmoney_datacenter(
            "RPT_DAILYBILLBOARD_DETAILS",
            filter_str=f'(TRADE_DATE="{date}")',
            page_size=120,
            sort_columns="BILLBOARD_NET_AMT",
        )

    def lockup_expiry(self, code: str, forward_days: int = 90) -> ProviderResult:
        ticker = _code6(code)
        return self.eastmoney_datacenter("RPT_LIFT_STAGE", filter_str=f'(SECURITY_CODE="{ticker}")', page_size=80, sort_columns="LIFT_DATE")

    def margin_trading(self, code: str) -> ProviderResult:
        ticker = _code6(code)
        return self.eastmoney_datacenter("RPTA_WEB_RZRQ_GGMX", filter_str=f'(SECURITY_CODE="{ticker}")', page_size=60, sort_columns="TRADE_DATE")

    def block_trade(self, code: str) -> ProviderResult:
        ticker = _code6(code)
        return self.eastmoney_datacenter("RPT_BLOCKTRADE_DET", filter_str=f'(SECURITY_CODE="{ticker}")', page_size=50, sort_columns="TRADE_DATE")

    def holder_num_change(self, code: str) -> ProviderResult:
        ticker = _code6(code)
        return self.eastmoney_datacenter("RPT_HOLDERNUMLATEST", filter_str=f'(SECURITY_CODE="{ticker}")', page_size=20, sort_columns="END_DATE")

    def dividend_history(self, code: str) -> ProviderResult:
        ticker = _code6(code)
        return self.eastmoney_datacenter("RPT_SHAREBONUS_DET", filter_str=f'(SECURITY_CODE="{ticker}")', page_size=50, sort_columns="EX_DIVIDEND_DATE")

    def industry_comparison(self, top_n: int = 20) -> ProviderResult:
        def fetch():
            url = "https://push2.eastmoney.com/api/qt/clist/get"
            params = {
                "pn": "1",
                "pz": str(max(top_n, 80)),
                "po": "1",
                "np": "1",
                "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                "fltt": "2",
                "invt": "2",
                "fid": "f3",
                "fs": "m:90+t:2",
                "fields": "f12,f14,f3,f62,f128,f140,f136,f104,f105",
            }
            data = _request_json(url, params, timeout=self.timeout)
            rows = ((data.get("data") or {}).get("diff")) or []
            return [
                {
                    "board_code": r.get("f12"),
                    "board_name": r.get("f14"),
                    "pct": _num(r.get("f3")),
                    "net_flow": _num(r.get("f62")),
                    "leader": r.get("f128"),
                    "leader_code": r.get("f140"),
                    "leader_pct": _num(r.get("f136")),
                    "up_count": _num(r.get("f104")),
                    "down_count": _num(r.get("f105")),
                }
                for r in rows
            ]

        return self._cached(f"industry_comparison_{top_n}", fetch, ttl=900)

    def eastmoney_stock_news(self, code: str, page_size: int = 20) -> ProviderResult:
        def fetch():
            cb = f"jQuery{int(time.time() * 1000)}"
            url = "https://search-api-web.eastmoney.com/search/jsonp"
            params = {
                "cb": cb,
                "param": json.dumps(
                    {
                        "uid": "",
                        "keyword": _code6(code),
                        "type": ["cmsArticleWebOld"],
                        "client": "web",
                        "clientType": "web",
                        "pageIndex": 1,
                        "pageSize": page_size,
                    },
                    ensure_ascii=False,
                ),
            }
            data = _request_json(url, params, timeout=self.timeout)
            items = data.get("result") or data.get("data") or []
            if isinstance(items, dict):
                items = items.get("cmsArticleWebOld") or items.get("items") or []
            return items

        return self._cached(f"em_stock_news_{_code6(code)}", fetch, ttl=1800)

    def cls_telegraph(self, page_size: int = 50) -> ProviderResult:
        def fetch():
            url = "https://www.cls.cn/nodeapi/telegraphList"
            data = _request_json(url, {"app": "CailianpressWeb", "page": 1, "rn": page_size}, headers={"User-Agent": UA, "Referer": "https://www.cls.cn/telegraph"}, timeout=self.timeout)
            return ((data.get("data") or {}).get("roll_data")) or []

        return self._cached(f"cls_telegraph_{page_size}", fetch, ttl=300)

    def eastmoney_global_news(self, page_size: int = 50) -> ProviderResult:
        def fetch():
            url = "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"
            params = {
                "client": "web",
                "biz": "web_724",
                "fastColumn": "102",
                "pageSize": page_size,
                "req_trace": str(int(time.time() * 1000)),
            }
            data = _request_json(url, params, timeout=self.timeout)
            return ((data.get("data") or {}).get("fastNewsList")) or []

        return self._cached(f"em_global_news_{page_size}", fetch, ttl=300)

    def eastmoney_stock_info(self, code: str) -> ProviderResult:
        def fetch():
            url = "https://push2.eastmoney.com/api/qt/stock/get"
            params = {
                "secid": _secid(code),
                "fields": "f57,f58,f84,f85,f116,f117,f127,f173,f187,f189,f190",
            }
            data = _request_json(url, params, timeout=self.timeout)
            return data.get("data") or {}

        return self._cached(f"em_stock_info_{_code6(code)}", fetch, ttl=3600)

    def cninfo_announcements(self, code: str, page_size: int = 30) -> ProviderResult:
        def fetch():
            ticker = _code6(code)
            prefix = _prefix(ticker).upper()
            org_prefix = "gssh" if prefix == "SH" else "gssz"
            payload = {
                "stock": f"{ticker},{org_prefix}{ticker}",
                "tabName": "fulltext",
                "pageSize": str(page_size),
                "pageNum": "1",
                "column": prefix,
                "category": "",
                "plate": "",
                "seDate": "",
                "searchkey": "",
                "secid": "",
                "sortName": "",
                "sortType": "",
                "isHLtitle": "true",
            }
            response = requests.post(
                "https://www.cninfo.com.cn/new/hisAnnouncement/query",
                data=payload,
                headers={"User-Agent": UA, "Referer": "https://www.cninfo.com.cn/new/disclosure", "Origin": "https://www.cninfo.com.cn"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            out = []
            for item in data.get("announcements") or []:
                out.append(
                    {
                        "title": re.sub(r"<[^>]+>", "", str(item.get("announcementTitle") or "")),
                        "date": _parse_any_date(item.get("announcementTime")),
                        "category": item.get("categoryName") or "",
                        "url": "https://www.cninfo.com.cn/new/disclosure/detail?annoId=" + str(item.get("announcementId") or ""),
                        "raw": item,
                    }
                )
            return out

        return self._cached(f"cninfo_announcements_{_code6(code)}", fetch, ttl=3600)

    def get_company_profile(self, code: str, **kwargs) -> ProviderResult:
        return self.eastmoney_stock_info(code)

    def get_valuation_metrics(self, code: str, **kwargs) -> ProviderResult:
        return self.tencent_quote([code])

    def get_moneyflow(self, code: str, **kwargs) -> ProviderResult:
        return self.stock_fund_flow_120d(code)

    def stock_signal_bundle(self, code: str, trade_date: str | None = None) -> dict:
        tasks = {
            "quote": lambda: self.tencent_quote([code]),
            "baidu_kline": lambda: self.baidu_kline_with_ma(code),
            "reports": lambda: self.eastmoney_reports(code),
            "eps_forecast": lambda: self.ths_eps_forecast(code),
            "hot_reason": lambda: self.ths_hot_reason(trade_date),
            "concepts": lambda: self.baidu_concept_blocks(code),
            "fund_flow_minute": lambda: self.eastmoney_fund_flow_minute(code),
            "fund_flow_120d": lambda: self.stock_fund_flow_120d(code),
            "dragon_tiger": lambda: self.dragon_tiger_board(code),
            "lockup": lambda: self.lockup_expiry(code),
            "margin": lambda: self.margin_trading(code),
            "block_trade": lambda: self.block_trade(code),
            "holders": lambda: self.holder_num_change(code),
            "dividends": lambda: self.dividend_history(code),
            "em_news": lambda: self.eastmoney_stock_news(code),
            "stock_info": lambda: self.eastmoney_stock_info(code),
            "announcements": lambda: self.cninfo_announcements(code),
        }
        warnings = []
        payload = {}
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {executor.submit(func): key for key, func in tasks.items()}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    result = future.result()
                    payload[key] = result.data
                    warnings.extend(result.warnings or [])
                except Exception as exc:
                    payload[key] = None
                    warnings.append({"source": self.name, "interface": key, "error_type": exc.__class__.__name__, "message": str(exc)})
        payload["warnings"] = warnings
        payload["source"] = "a-stock-data V3.1 direct public endpoints"
        payload["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return payload

    def market_signal_bundle(self, trade_date: str | None = None) -> dict:
        tasks = {
            "hot_reason": lambda: self.ths_hot_reason(trade_date),
            "northbound": self.hsgt_realtime,
            "daily_dragon_tiger": lambda: self.daily_dragon_tiger(trade_date),
            "industry": lambda: self.industry_comparison(80),
            "index_quotes": lambda: self.tencent_quote(["000001", "000300", "399006", "510050", "510300"]),
            "cls": lambda: self.cls_telegraph(50),
            "global_news": lambda: self.eastmoney_global_news(50),
        }
        warnings = []
        payload = {}
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(func): key for key, func in tasks.items()}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    result = future.result()
                    payload[key] = result.data
                    warnings.extend(result.warnings or [])
                except Exception as exc:
                    payload[key] = None
                    warnings.append({"source": self.name, "interface": key, "error_type": exc.__class__.__name__, "message": str(exc)})
        payload["warnings"] = warnings
        payload["source"] = "a-stock-data V3.1 direct public endpoints"
        payload["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return payload
