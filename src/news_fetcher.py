from __future__ import annotations

import html
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime
from urllib.parse import urljoin, urlparse, urlunparse

import pandas as pd

from .cache_utils import FileCache, safe_fetch
from .providers.a_stock_data_provider import AStockDataProvider
from .utils import display_code, ensure_dirs, normalize_a_share_code

# Disable akshare news fetching due to high latency, large payload download, and hanging endpoints.
# Rely on robust, lightweight, and direct public endpoints from Eastmoney and Cailianpress instead.
ak = None


UA = "Mozilla/5.0 (Jocket news reference)"

EVENT_KEYWORDS = (
    "公告", "业绩", "预告", "净利润", "营收", "订单", "合同", "中标", "签署", "合作",
    "回购", "增持", "减持", "解禁", "重组", "并购", "定增", "融资", "分红", "股东",
    "监管", "问询", "处罚", "评级", "研报", "机构", "涨停", "异动",
)

THEME_KEYWORDS = (
    "政策", "行业", "概念", "题材", "涨价", "景气", "需求", "出口", "国产替代",
    "人工智能", "AI", "算力", "芯片", "半导体", "新能源", "储能", "机器人",
)

LOW_VALUE_TITLES = {
    "首页概览", "资金流向", "公司资料", "新闻公告", "财务分析", "经营分析", "股东股本",
    "公司大事", "行业分析", "行情走势", "最新消息", "公司公告", "相关研报", "研究报告",
    "机构评级", "个股研报", "同行业研报", "更多", "更多>", "更多 >",
}


def _clean_text(text: str, limit: int | None = None) -> str:
    text = html.unescape(str(text or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] if limit else text


def _normalized_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", parsed.query, ""))


def _classify(url: str, title: str) -> str:
    norm = _normalized_url(url).lower()
    if "notice.10jqka.com.cn" in norm or "公告" in title:
        return "公告"
    if "report" in norm or "研报" in title or "评级" in title:
        return "研报"
    if "doctor.10jqka.com.cn" in norm or "诊股" in title:
        return "诊股"
    if any(host in norm for host in ("news.10jqka.com.cn", "stock.10jqka.com.cn", "field.10jqka.com.cn")):
        return "新闻"
    return "公开信息"


def _extract_date(title: str, url: str) -> date | None:
    text = f"{title} {url}"
    for pattern in (r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", r"(20\d{2})(\d{2})(\d{2})"):
        match = re.search(pattern, text)
        if not match:
            continue
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except Exception:
            pass
    return None


def _extract_entries(text: str, base_url: str) -> list[dict]:
    entries = []
    seen = set()
    for href, inner in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', text, re.I | re.S):
        title = _clean_text(inner, 120)
        if not href or not title or title in LOW_VALUE_TITLES or len(title) < 4:
            continue
        url = urljoin(base_url, html.unescape(href.strip()))
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            continue
        marker = (title, _normalized_url(url))
        if marker in seen:
            continue
        seen.add(marker)
        item_date = _extract_date(title, url)
        entries.append(
            {
                "title": title,
                "url": url,
                "kind": _classify(url, title),
                "date": item_date.isoformat() if item_date else None,
            }
        )
    return entries[:120]


def _extract_meta(text: str) -> list[str]:
    out = []
    for pattern in (
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']keywords["\'][^>]+content=["\']([^"\']+)["\']',
    ):
        match = re.search(pattern, text, re.I)
        if match:
            out.append(_clean_text(match.group(1), 160))
    return [item for item in out if item]


def _recency_score(item_date: str | None) -> tuple[int, str]:
    if not item_date:
        return 5, "未识别日期"
    try:
        days = (date.today() - datetime.strptime(item_date, "%Y-%m-%d").date()).days
    except Exception:
        return 5, "日期解析失败"
    if days <= 7:
        return 15, "7日内"
    if days <= 30:
        return 10, "30日内"
    if days <= 120:
        return 5, "120日内"
    return 0, "较早信息"


class NewsFetcher:
    """Fetch public news/notice references and score relevance to stocks or themes."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        ensure_dirs()
        self.cache = FileCache("data/cache")
        self.timeout = float(self.config.get("data", {}).get("timeout", 12))

    def fetch(self, code: str, name: str | None = None, boards: list[str] | None = None) -> dict:
        ticker = display_code(normalize_a_share_code(code))
        cache_key = f"news_stock_{ticker}_{datetime.now().strftime('%Y%m%d_%H')}"
        ttl = int(self.config.get("news", {}).get("ttl_seconds", 1800))
        cached = self.cache.get_pickle("news", cache_key, ttl_seconds=ttl)
        if cached:
            return cached

        errors: list[dict] = []
        entries: list[dict] = []
        highlights: list[str] = []

        if ak is not None:
            em_news, err = safe_fetch(
                "akshare",
                "stock_news_em",
                lambda: ak.stock_news_em(symbol=ticker),
                retries=1,
                min_interval=1.0,
                cache=self.cache,
            )
            errors.extend(err)
            entries.extend(self._normalize_stock_news_em(em_news))
        try:
            provider = AStockDataProvider(self.cache, self.config)
            result = provider.eastmoney_stock_news(ticker)
            errors.extend(result.warnings or [])
            entries.extend(self._normalize_a_stock_em_news(result.data))
        except Exception as exc:
            errors.append({"source": "a-stock-data", "interface": "eastmoney_stock_news", "error_type": exc.__class__.__name__, "message": str(exc)})

        base_url = f"https://stockpage.10jqka.com.cn/{ticker}/"
        text, err = safe_fetch(
            "ths",
            "stockpage_news",
            lambda: self._fetch_text(base_url),
            retries=1,
            min_interval=0.8,
            cache=self.cache,
        )
        errors.extend(err)
        entries.extend(_extract_entries(text or "", base_url) if text else [])
        generic_titles = {ticker}
        if name:
            generic_titles.update({name, f"{name} {ticker}", f"{ticker} {name}"})
        entries = [entry for entry in entries if entry.get("title") not in generic_titles]
        highlights.extend(_extract_meta(text or "") if text else [])
        global_items, global_errors = self._fetch_global_items()
        errors.extend(global_errors)
        entries.extend(global_items)

        entries = self._dedupe(entries)
        scored = [self._score_entry(entry, ticker, name, boards or [], highlights) for entry in entries]
        scored = [item for item in scored if item.get("relevance_score", 0) >= int(self.config.get("news", {}).get("min_relevance", 20))]
        scored = sorted(scored, key=lambda item: (item["relevance_score"], item.get("date") or ""), reverse=True)
        top_items = scored[: int(self.config.get("news", {}).get("max_items", 8))]
        heat_score = self._aggregate_score(top_items, highlights)
        payload = {
            "available": bool(top_items or highlights),
            "ticker": ticker,
            "source": self._source_summary(top_items) or "东方财富 + 同花顺 + 财联社 + 公开快讯",
            "summary": self._summary(top_items, highlights),
            "heat_score": heat_score,
            "items": top_items,
            "highlights": highlights[:4],
            "errors": errors,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.cache.set_pickle("news", cache_key, payload)
        return payload

    def fetch_topics(self, keywords: list[str], *, label: str = "市场消息面", max_items: int | None = None) -> dict:
        clean_keywords = [str(k).strip() for k in keywords if str(k or "").strip()]
        clean_keywords = list(dict.fromkeys(clean_keywords))[:20]
        cache_key = f"news_topics_{'_'.join(clean_keywords[:6])}_{datetime.now().strftime('%Y%m%d_%H')}"
        ttl = int(self.config.get("news", {}).get("ttl_seconds", 1800))
        cached = self.cache.get_pickle("news", cache_key, ttl_seconds=ttl)
        if cached:
            return cached

        global_items, errors = self._fetch_global_items()
        scored = [self._score_topic_entry(entry, clean_keywords) for entry in global_items]
        scored = [item for item in scored if item.get("relevance_score", 0) >= int(self.config.get("news", {}).get("topic_min_relevance", 18))]
        scored = sorted(scored, key=lambda item: (item["relevance_score"], item.get("date") or ""), reverse=True)
        top_items = scored[: int(max_items or self.config.get("news", {}).get("max_items", 12))]
        payload = {
            "available": bool(top_items),
            "ticker": "",
            "source": self._source_summary(top_items) or "财联社 + 同花顺 + 东方财富公开快讯",
            "summary": self._summary(top_items, []),
            "heat_score": self._aggregate_score(top_items, []),
            "items": top_items,
            "highlights": clean_keywords[:8],
            "errors": errors,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "label": label,
        }
        self.cache.set_pickle("news", cache_key, payload)
        return payload

    def _fetch_text(self, url: str) -> str:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": UA, "Referer": "https://stockpage.10jqka.com.cn/"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw = resp.read()
        for enc in ("utf-8", "gb18030", "gbk"):
            try:
                return raw.decode(enc)
            except Exception:
                pass
        return raw.decode("utf-8", errors="ignore")

    def _fetch_global_items(self) -> tuple[list[dict], list[dict]]:
        cache_key = f"global_news_{datetime.now().strftime('%Y%m%d_%H')}"
        cached = self.cache.get_pickle("news", cache_key, ttl_seconds=int(self.config.get("news", {}).get("global_ttl_seconds", 900)))
        if cached:
            return cached.get("items", []), cached.get("errors", [])

        errors: list[dict] = []
        entries: list[dict] = []
        if ak is not None:
            sources = [
                ("财联社电报", "stock_info_global_cls", lambda: ak.stock_info_global_cls(symbol="全部")),
                ("同花顺财经直播", "stock_info_global_ths", lambda: ak.stock_info_global_ths()),
                ("东方财富快讯", "stock_info_global_em", lambda: ak.stock_info_global_em()),
            ]
            for source_name, interface, func in sources:
                df, err = safe_fetch("akshare", interface, func, retries=1, min_interval=1.0, cache=self.cache)
                errors.extend(err)
                entries.extend(self._normalize_global_news(df, source_name))
        try:
            provider = AStockDataProvider(self.cache, self.config)
            cls_result = provider.cls_telegraph(50)
            em_result = provider.eastmoney_global_news(50)
            errors.extend(cls_result.warnings or [])
            errors.extend(em_result.warnings or [])
            entries.extend(self._normalize_a_stock_cls(cls_result.data))
            entries.extend(self._normalize_a_stock_global_news(em_result.data))
        except Exception as exc:
            errors.append({"source": "a-stock-data", "interface": "global_news", "error_type": exc.__class__.__name__, "message": str(exc)})
        entries.extend(self._fetch_extra_public_feeds(errors))
        payload = {"items": self._dedupe(entries), "errors": errors}
        self.cache.set_pickle("news", cache_key, payload)
        return payload["items"], payload["errors"]

    def _fetch_extra_public_feeds(self, errors: list[dict]) -> list[dict]:
        feeds = self.config.get("news", {}).get("extra_public_feeds", [])
        entries: list[dict] = []
        for feed in feeds:
            if not isinstance(feed, dict) or feed.get("type", "rss") != "rss" or not feed.get("url"):
                continue
            source = str(feed.get("name") or "第三方RSS")
            text, err = safe_fetch(
                "third_party_news",
                source,
                lambda url=feed["url"]: self._fetch_text(url),
                retries=1,
                min_interval=0.5,
                cache=self.cache,
            )
            errors.extend(err)
            if text:
                entries.extend(self._parse_rss_items(text, source))
        return entries

    @staticmethod
    def _parse_rss_items(text: str, source: str) -> list[dict]:
        try:
            root = ET.fromstring(text)
        except Exception:
            return []
        rows = []
        for item in root.findall(".//item")[:80]:
            title = _clean_text(item.findtext("title"), 160)
            content = _clean_text(item.findtext("description"), 360)
            if not title and not content:
                continue
            rows.append(
                {
                    "title": title or content[:80],
                    "content": content,
                    "url": str(item.findtext("link") or ""),
                    "kind": "第三方RSS",
                    "date": _parse_any_date(item.findtext("pubDate")),
                    "source": source,
                }
            )
        return rows

    @staticmethod
    def _normalize_stock_news_em(df: pd.DataFrame | None) -> list[dict]:
        if df is None or df.empty:
            return []
        rows = []
        for _, row in df.head(60).iterrows():
            title = _clean_text(row.get("新闻标题"), 140)
            if not title:
                continue
            rows.append(
                {
                    "title": title,
                    "content": _clean_text(row.get("新闻内容"), 280),
                    "url": str(row.get("新闻链接") or ""),
                    "kind": _classify(str(row.get("新闻链接") or ""), title),
                    "date": _parse_any_date(row.get("发布时间")),
                    "source": str(row.get("文章来源") or "东方财富个股新闻"),
                }
            )
        return rows

    @staticmethod
    def _normalize_a_stock_em_news(items) -> list[dict]:
        rows = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            title = _clean_text(item.get("title") or item.get("Title") or item.get("artTitle") or item.get("newsTitle"), 160)
            content = _clean_text(item.get("content") or item.get("summary") or item.get("digest") or item.get("Art_ShowTime"), 320)
            if not title and not content:
                continue
            rows.append(
                {
                    "title": title or content[:80],
                    "content": content,
                    "url": str(item.get("url") or item.get("Url") or item.get("artUrl") or item.get("link") or ""),
                    "kind": "新闻",
                    "date": _parse_any_date(item.get("date") or item.get("showTime") or item.get("publishTime") or item.get("Art_ShowTime")),
                    "source": str(item.get("source") or item.get("mediaName") or "东财个股新闻"),
                }
            )
        return rows

    @staticmethod
    def _normalize_a_stock_cls(items) -> list[dict]:
        rows = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            title = _clean_text(item.get("title") or item.get("content") or item.get("descr"), 180)
            content = _clean_text(item.get("content") or item.get("descr") or title, 360)
            if not title:
                continue
            ts = item.get("ctime") or item.get("time") or item.get("created_at")
            if isinstance(ts, (int, float)) and ts > 1000000000:
                ts = pd.to_datetime(ts, unit="s", errors="coerce")
            rows.append(
                {
                    "title": title,
                    "content": content,
                    "url": str(item.get("shareurl") or item.get("url") or ""),
                    "kind": "财联社电报",
                    "date": _parse_any_date(ts),
                    "source": "财联社直连",
                }
            )
        return rows

    @staticmethod
    def _normalize_a_stock_global_news(items) -> list[dict]:
        rows = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            title = _clean_text(item.get("title") or item.get("newsTitle") or item.get("digest"), 180)
            content = _clean_text(item.get("summary") or item.get("digest") or item.get("content") or title, 360)
            if not title:
                continue
            rows.append(
                {
                    "title": title,
                    "content": content,
                    "url": str(item.get("url") or item.get("newsUrl") or ""),
                    "kind": "7x24",
                    "date": _parse_any_date(item.get("showTime") or item.get("time") or item.get("publishTime")),
                    "source": "东财全球资讯直连",
                }
            )
        return rows

    @staticmethod
    def _normalize_global_news(df: pd.DataFrame | None, source: str) -> list[dict]:
        if df is None or df.empty:
            return []
        rows = []
        for _, row in df.head(160).iterrows():
            title = _clean_text(row.get("标题"), 160)
            content = _clean_text(row.get("内容", row.get("摘要", "")), 360)
            if not title and not content:
                continue
            date_text = row.get("发布时间") or row.get("发布日期")
            rows.append(
                {
                    "title": title or content[:80],
                    "content": content,
                    "url": str(row.get("链接") or ""),
                    "kind": "快讯" if source != "财联社电报" else "财联社电报",
                    "date": _parse_any_date(date_text),
                    "source": source,
                }
            )
        return rows

    @staticmethod
    def _dedupe(entries: list[dict]) -> list[dict]:
        seen = set()
        out = []
        for entry in entries:
            title = _clean_text(entry.get("title"), 140)
            if not title:
                continue
            marker = (title, _normalized_url(str(entry.get("url") or "")))
            if marker in seen:
                continue
            seen.add(marker)
            item = dict(entry)
            item["title"] = title
            item.setdefault("source", "公开信息")
            out.append(item)
        return out

    def _score_entry(self, entry: dict, ticker: str, name: str | None, boards: list[str], highlights: list[str]) -> dict:
        title = entry.get("title", "")
        content = entry.get("content", "")
        text = title
        context_text = " ".join([title, content])
        score = 0
        reasons = []

        if ticker in context_text:
            score += 35
            reasons.append("消息直接包含股票代码")
        if name and name in context_text:
            score += 35
            reasons.append("消息直接包含股票名称")

        event_hits = [kw for kw in EVENT_KEYWORDS if kw in text]
        if event_hits:
            score += min(25, 8 + len(event_hits) * 3)
            reasons.append("包含事件词：" + "、".join(event_hits[:4]))

        board_hits = [board for board in boards if board and str(board) in context_text]
        if board_hits:
            score += min(20, 10 + len(board_hits) * 4)
            reasons.append("匹配所属板块：" + "、".join(map(str, board_hits[:3])))

        theme_hits = [kw for kw in THEME_KEYWORDS if kw in context_text]
        if theme_hits:
            score += min(12, 4 + len(theme_hits) * 2)
            reasons.append("包含行业/题材词：" + "、".join(theme_hits[:4]))

        if entry.get("kind") in {"公告", "研报"}:
            score += 8
            reasons.append(f"{entry.get('kind')}类信息权重更高")
        elif entry.get("kind") == "新闻":
            score += 5

        recency, recency_reason = _recency_score(entry.get("date"))
        score += recency
        if recency:
            reasons.append(f"时效性：{recency_reason}")

        if not reasons:
            reasons.append("弱相关公开信息，仅作背景参考")
        out = dict(entry)
        out["relevance_score"] = int(max(0, min(100, score)))
        out["relevance_reason"] = "；".join(reasons)
        return out

    def _score_topic_entry(self, entry: dict, keywords: list[str]) -> dict:
        title = entry.get("title", "")
        content = entry.get("content", "")
        text = " ".join([title, content])
        score = 0
        reasons = []
        keyword_hits = [kw for kw in keywords if kw and kw in text]
        if keyword_hits:
            score += min(55, 25 + len(keyword_hits) * 8)
            reasons.append("匹配关键词：" + "、".join(keyword_hits[:5]))
        event_hits = [kw for kw in EVENT_KEYWORDS if kw in text]
        if event_hits:
            score += min(18, 6 + len(event_hits) * 2)
            reasons.append("包含事件词：" + "、".join(event_hits[:4]))
        theme_hits = [kw for kw in THEME_KEYWORDS if kw in text]
        if theme_hits:
            score += min(16, 4 + len(theme_hits) * 2)
            reasons.append("包含行业/题材词：" + "、".join(theme_hits[:4]))
        if entry.get("source") == "财联社电报":
            score += 8
            reasons.append("财联社电报源")
        recency, recency_reason = _recency_score(entry.get("date"))
        score += recency
        if recency:
            reasons.append(f"时效性：{recency_reason}")
        if not reasons:
            reasons.append("弱相关公开快讯，仅作市场背景")
        out = dict(entry)
        out["relevance_score"] = int(max(0, min(100, score)))
        out["relevance_reason"] = "；".join(reasons)
        return out

    @staticmethod
    def _aggregate_score(items: list[dict], highlights: list[str]) -> float:
        if not items:
            return 10.0 if highlights else 0.0
        scores = [float(item.get("relevance_score", 0) or 0) for item in items[:5]]
        top = max(scores)
        avg = sum(scores) / len(scores)
        breadth = min(10, len([s for s in scores if s >= 40]) * 2)
        return round(min(100, top * 0.55 + avg * 0.35 + breadth), 1)

    @staticmethod
    def _summary(items: list[dict], highlights: list[str]) -> str:
        titles = [item.get("title", "") for item in items[:3] if item.get("title")]
        parts = titles or highlights[:2]
        return "；".join(parts)[:260] if parts else "暂无可用公开消息摘要"

    @staticmethod
    def _source_summary(items: list[dict]) -> str:
        sources = [str(item.get("source") or "").strip() for item in items if item.get("source")]
        return " + ".join(list(dict.fromkeys(sources))[:5])


def _parse_any_date(value) -> str | None:
    if value is None or value == "":
        return None
    dt = pd.to_datetime(value, errors="coerce")
    if pd.isna(dt):
        return None
    return dt.strftime("%Y-%m-%d")


def news_items_to_frame(payload: dict) -> pd.DataFrame:
    items = payload.get("items", []) if payload else []
    if not items:
        return pd.DataFrame()
    cols = ["source", "kind", "date", "title", "relevance_score", "relevance_reason", "url"]
    frame = pd.DataFrame(items)
    for col in cols:
        if col not in frame.columns:
            frame[col] = ""
    return frame[cols]
