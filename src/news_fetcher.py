from __future__ import annotations

import html
import re
import urllib.request
from datetime import date, datetime
from urllib.parse import urljoin, urlparse, urlunparse

import pandas as pd

from .cache_utils import FileCache, safe_fetch
from .utils import display_code, ensure_dirs, normalize_a_share_code


UA = "Mozilla/5.0 (stock-picker-ui news reference)"

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
    """Fetch public news/notice references and score their relevance to a stock."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        ensure_dirs()
        self.cache = FileCache("data/cache")
        self.timeout = float(self.config.get("data", {}).get("timeout", 12))

    def fetch(self, code: str, name: str | None = None, boards: list[str] | None = None) -> dict:
        ticker = display_code(normalize_a_share_code(code))
        cache_key = f"news_{ticker}_{datetime.now().strftime('%Y%m%d_%H')}"
        ttl = int(self.config.get("news", {}).get("ttl_seconds", 1800))
        cached = self.cache.get_pickle("news", cache_key, ttl_seconds=ttl)
        if cached:
            return cached

        errors: list[dict] = []
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

        entries = _extract_entries(text or "", base_url) if text else []
        generic_titles = {ticker}
        if name:
            generic_titles.update({name, f"{name} {ticker}", f"{ticker} {name}"})
        entries = [entry for entry in entries if entry.get("title") not in generic_titles]
        highlights = _extract_meta(text or "") if text else []
        scored = [self._score_entry(entry, ticker, name, boards or [], highlights) for entry in entries]
        scored = sorted(scored, key=lambda item: item["relevance_score"], reverse=True)
        top_items = scored[: int(self.config.get("news", {}).get("max_items", 8))]
        heat_score = self._aggregate_score(top_items, highlights)
        payload = {
            "available": bool(top_items or highlights),
            "ticker": ticker,
            "source": "同花顺公开页面",
            "summary": self._summary(top_items, highlights),
            "heat_score": heat_score,
            "items": top_items,
            "highlights": highlights[:4],
            "errors": errors,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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

    def _score_entry(self, entry: dict, ticker: str, name: str | None, boards: list[str], highlights: list[str]) -> dict:
        title = entry.get("title", "")
        text = title
        context_text = " ".join([title, " ".join(highlights)])
        score = 0
        reasons = []

        if ticker in text:
            score += 35
            reasons.append("标题/摘要直接包含股票代码")
        if name and name in text:
            score += 35
            reasons.append("标题/摘要直接包含股票名称")

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


def news_items_to_frame(payload: dict) -> pd.DataFrame:
    items = payload.get("items", []) if payload else []
    if not items:
        return pd.DataFrame()
    return pd.DataFrame(items)[["kind", "date", "title", "relevance_score", "relevance_reason", "url"]]
