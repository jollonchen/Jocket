#!/usr/bin/env python3
import html
import json
import re
from datetime import date, datetime
import urllib.request
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

UA = "Mozilla/5.0 (OpenClaw Skill a-share-stock-picker)"
TIMEOUT = 12
MAX_MORE_LINKS = 4
MAX_ARTICLE_LINKS = 6
MAX_PAGINATION_PAGES = 3
MAX_USEFUL_ITEMS = 200

GENERIC_TITLES = {
    "更多",
    "更多>",
    "更多 >",
    "更多>>",
    "首页概览",
    "资金流向",
    "公司资料",
    "新闻公告",
    "财务分析",
    "经营分析",
    "股东股本",
    "主力持仓",
    "公司大事",
    "分红融资",
    "价值分析",
    "行业分析",
    "行情走势",
    "最新消息",
    "公司公告",
    "相关研报",
    "行业新闻",
    "研究报告",
    "机构评级",
    "机构预测",
    "同花顺推荐",
    "数据中心",
    "大单追踪",
    "融资融券",
    "新股申购",
    "行情中心",
    "沪深市场",
    "香港市场",
    "美国市场",
    "全球市场",
    "行业风云",
    "i问董秘",
    "最新动态",
    "股东研究",
    "股本结构",
    "资本运作",
    "盈利预测",
    "行业对比",
    "[成分股]",
}

ARTICLE_HOST_HINTS = (
    "notice.10jqka.com.cn",
    "stock.10jqka.com.cn",
    "news.10jqka.com.cn",
    "field.10jqka.com.cn",
    "fund.10jqka.com.cn",
    "doctor.10jqka.com.cn",
)

EXCLUDED_URL_HINTS = (
    "upass.10jqka.com.cn",
    "activity.10jqka.com.cn",
    "javascript:",
    "#",
)

FRESHNESS_DAYS = {
    "news": 30,
    "report": 120,
    "notice": 365,
    "doctor": 180,
    "other": 90,
}

LOW_VALUE_KEYWORDS = (
    "软件下载",
    "返回首页",
    "财富先锋",
    "频道资讯",
    "运营许可",
    "量化回测",
    "银柿财经",
    "退市整理板",
    "连续上涨",
    "资金流向排名",
    "更多个股解读",
    "参与调查",
)

DECISION_KEYWORDS = (
    "公告",
    "融资",
    "资金",
    "订单",
    "签署",
    "评级",
    "业绩",
    "回购",
    "增持",
    "减持",
    "股东",
    "机构",
    "概念",
    "主营",
    "行业",
    "诊股",
    "研报",
    "解禁",
    "异动",
    "涨停",
    "合作",
)

SECTION_PATTERNS = [
    ("涉及概念", r"涉及概念[:：]\s*([^。；]{4,80})"),
    ("主营业务", r"主营业务[:：]\s*([^。；]{4,120})"),
    ("所属地域", r"所属地域[:：]\s*([^。；]{2,30})"),
    ("综合判断", r"综合判断[:：]?\s*([^。]{4,80})"),
    ("短期趋势", r"短期趋势[:：]?\s*([^。]{4,80})"),
    ("中期趋势", r"中期趋势[:：]?\s*([^。]{4,80})"),
    ("长期趋势", r"长期趋势[:：]?\s*([^。]{4,120})"),
]


def fetch_text(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Referer": "https://stockpage.10jqka.com.cn/",
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        raw = resp.read()
        for enc in ("utf-8", "gb18030", "gbk", "latin1"):
            try:
                return raw.decode(enc)
            except Exception:
                pass
    return raw.decode("utf-8", errors="ignore")


def clean_text(text, limit=None):
    text = html.unescape(str(text or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"[|_]+", " ", text)
    if limit:
        return text[:limit]
    return text


def unique_keep(items, key=None, limit=None):
    seen = set()
    out = []
    for item in items:
        marker = key(item) if key else item
        if not marker or marker in seen:
            continue
        seen.add(marker)
        out.append(item)
        if limit and len(out) >= limit:
            break
    return out


def extract_title(text):
    m = re.search(r"<title>(.*?)</title>", text, re.I | re.S)
    if not m:
        return None
    title = clean_text(m.group(1), limit=120)
    return title or None


def extract_meta_description(text):
    m = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        text,
        re.I,
    )
    if not m:
        return None
    desc = clean_text(m.group(1), limit=180)
    return desc or None


def normalized_url(url):
    parsed = urlparse(url)
    if not parsed.scheme:
        return None
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", parsed.query, ""))


def extract_anchor_entries(text, base_url):
    entries = []
    for href, inner in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', text, re.I | re.S):
        href = html.unescape(href.strip())
        label = clean_text(inner, limit=120)
        if not href or not label:
            continue
        if any(hint in href for hint in EXCLUDED_URL_HINTS):
            continue
        if label in GENERIC_TITLES:
            continue
        if len(label) < 4:
            continue
        full_url = urljoin(base_url, href)
        kind = classify_item(full_url, label)
        dt = extract_item_date(label, full_url)
        entries.append(
            {
                "title": label,
                "url": full_url,
                "kind": kind,
                "date": dt.isoformat() if dt else None,
            }
        )
    return unique_keep(entries, key=lambda item: (item["title"], normalized_url(item["url"])), limit=120)


def extract_more_links(text, base_url):
    links = []
    for href, inner in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', text, re.I | re.S):
        label = clean_text(inner, limit=30)
        href = html.unescape(href.strip())
        if "更多" not in label or not href:
            continue
        if any(hint in href for hint in EXCLUDED_URL_HINTS):
            continue
        links.append(urljoin(base_url, href))
    return unique_keep(links, key=normalized_url, limit=MAX_MORE_LINKS)


def extract_field_snippets(text):
    plain = clean_text(text)
    snippets = []
    for label, pattern in SECTION_PATTERNS:
        m = re.search(pattern, plain)
        if not m:
            continue
        snippets.append(f"{label}：{clean_text(m.group(1), limit=120)}")
    return unique_keep(snippets, limit=8)


def is_article_link(url):
    norm = normalized_url(url) or ""
    if any(hint in norm for hint in EXCLUDED_URL_HINTS):
        return False
    return any(host in norm for host in ARTICLE_HOST_HINTS)


def build_paged_urls(url, max_pages=MAX_PAGINATION_PAGES):
    urls = [url]
    parsed = urlparse(url)
    if not parsed.scheme:
        return urls
    base_query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    candidates = ["page", "pageNum"]
    built = []
    for page in range(2, max_pages + 1):
        for param in candidates:
            query = dict(base_query)
            query[param] = str(page)
            new_url = urlunparse(
                (parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(query), parsed.fragment)
            )
            built.append(new_url)
    return unique_keep(urls + built, key=normalized_url)


def summarize(context):
    parts = []
    for desc in context.get("descriptions", [])[:2]:
        parts.append(desc)
    for snippet in context.get("sectionHighlights", [])[:2]:
        parts.append(snippet)
    for title in context.get("titles", [])[:3]:
        parts.append(title)
    return "；".join(unique_keep([clean_text(part, limit=100) for part in parts if part], limit=6))[:260]


def classify_item(url, title):
    norm = (normalized_url(url) or "").lower()
    title = clean_text(title, limit=120)
    if "notice.10jqka.com.cn" in norm or "pubnote" in norm or "公告" in title:
        return "notice"
    if "report" in norm or "研报" in title or "评级" in title or "预测" in title:
        return "report"
    if "doctor.10jqka.com.cn" in norm or "诊股" in title:
        return "doctor"
    if any(host in norm for host in ("news.10jqka.com.cn", "stock.10jqka.com.cn", "field.10jqka.com.cn", "fund.10jqka.com.cn")):
        return "news"
    return "other"


def extract_item_date(title, url):
    norm_title = clean_text(title, limit=120)
    for pattern in (
        r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})",
        r"(20\d{2})(\d{2})(\d{2})",
    ):
        m = re.search(pattern, norm_title)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except Exception:
                pass
    for pattern in (
        r"/(20\d{6})/",
        r"date=(20\d{8})",
        r"reportDate=(20\d{8})",
    ):
        m = re.search(pattern, url)
        if m:
            try:
                return datetime.strptime(m.group(1), "%Y%m%d").date()
            except Exception:
                pass
    m = re.search(r"(^|[^0-9])(\d{2})[/-](\d{2})([^0-9]|$)", norm_title)
    if m:
        month = int(m.group(2))
        day = int(m.group(3))
        year = date.today().year
        try:
            guess = date(year, month, day)
            if guess > date.today():
                guess = date(year - 1, month, day)
            return guess
        except Exception:
            return None
    return None


def item_is_fresh(item):
    item_date = item.get("date")
    kind = item.get("kind") or "other"
    if not item_date:
        return kind in {"notice", "doctor", "other"}
    try:
        dt = datetime.strptime(item_date, "%Y-%m-%d").date()
    except Exception:
        return False
    return (date.today() - dt).days <= FRESHNESS_DAYS.get(kind, 90)


def item_score(item):
    kind = item.get("kind") or "other"
    score = {
        "notice": 120,
        "report": 105,
        "news": 95,
        "doctor": 75,
        "other": 60,
    }.get(kind, 50)
    title = item.get("title") or ""
    if any(keyword in title for keyword in LOW_VALUE_KEYWORDS):
        return 0
    if any(keyword in title for keyword in ("公告", "融资", "订单", "签署", "评级", "增持", "回购", "业绩")):
        score += 18
    if any(keyword in title for keyword in ("个股解读", "参与调查", "更多")):
        score -= 20
    if item.get("date"):
        try:
            days = (date.today() - datetime.strptime(item["date"], "%Y-%m-%d").date()).days
            score += max(0, 30 - min(days, 30))
        except Exception:
            pass
    elif kind in {"news", "report"}:
        score -= 15
    if kind == "other" and not item.get("date") and not any(keyword in title for keyword in DECISION_KEYWORDS):
        score -= 35
    return score


def filter_useful_items(items):
    unique_items = unique_keep(items, key=lambda item: (item["title"], normalized_url(item["url"])))
    filtered = []
    for item in unique_items:
        if not item_is_fresh(item):
            continue
        scored = dict(item)
        scored["score"] = item_score(item)
        if scored["score"] < 60:
            continue
        filtered.append(scored)
    filtered.sort(key=lambda item: (-item["score"], item.get("date") or "", item["title"]))
    return filtered[:MAX_USEFUL_ITEMS]


def useful_title(title):
    title = clean_text(title, limit=120)
    if not title:
        return False
    if title in GENERIC_TITLES or title == "同花顺问财":
        return False
    if any(keyword in title for keyword in LOW_VALUE_KEYWORDS):
        return False
    return True


def build_context(ticker):
    ticker = ticker[-6:]
    context = {
        "ticker": ticker,
        "titles": [],
        "descriptions": [],
        "sectionHighlights": [],
        "items": [],
        "pages": [],
        "pageCount": 0,
        "paginatedPageCount": 0,
        "articlePageCount": 0,
        "errors": [],
    }
    seen_urls = set()
    article_links = []
    more_links = []

    def collect_page(url, kind, page_no=1):
        norm = normalized_url(url)
        if not norm or norm in seen_urls:
            return []
        seen_urls.add(norm)
        try:
            text = fetch_text(url)
        except (URLError, HTTPError, TimeoutError, Exception) as exc:
            context["errors"].append(f"{kind} {url}: {exc}")
            return []

        title = extract_title(text)
        desc = extract_meta_description(text)
        anchors = extract_anchor_entries(text, url)
        snippets = extract_field_snippets(text)

        if title:
            context["titles"].append(title)
        if desc:
            context["descriptions"].append(desc)
        context["items"].extend(anchors)
        context["sectionHighlights"].extend(snippets)
        if title or anchors:
            context["pages"].append(
                {
                    "url": url,
                    "kind": kind,
                    "pageNo": page_no,
                    "title": title,
                    "itemCount": len(anchors),
                }
            )

        if kind == "article":
            context["articlePageCount"] += 1
        if kind == "paged":
            context["paginatedPageCount"] += 1

        return anchors

    base_urls = [
        f"https://stockpage.10jqka.com.cn/{ticker}/",
        f"https://basic.10jqka.com.cn/{ticker}/",
    ]

    for url in base_urls:
        anchors = collect_page(url, "base")
        if not anchors:
            continue
        article_links.extend([item["url"] for item in anchors if is_article_link(item["url"])])
        try:
            base_html = fetch_text(url)
            more_links.extend(extract_more_links(base_html, url))
        except (URLError, HTTPError, TimeoutError, Exception) as exc:
            context["errors"].append(f"more-links {url}: {exc}")

    for more_url in unique_keep(more_links, key=normalized_url, limit=MAX_MORE_LINKS):
        for idx, paged_url in enumerate(build_paged_urls(more_url), start=1):
            anchors = collect_page(paged_url, "paged", page_no=idx)
            if not anchors and idx > 1:
                break
            article_links.extend([item["url"] for item in anchors if is_article_link(item["url"])])

    for article_url in unique_keep(article_links, key=normalized_url, limit=MAX_ARTICLE_LINKS):
        collect_page(article_url, "article")

    context["items"] = filter_useful_items(context["items"])
    context["titles"] = unique_keep(
        [clean_text(title, limit=120) for title in context["titles"] if useful_title(title)] +
        [item["title"] for item in context["items"]],
        limit=40,
    )
    context["descriptions"] = unique_keep(
        [clean_text(desc, limit=180) for desc in context["descriptions"] if clean_text(desc) and clean_text(desc) != "暂无"],
        limit=8,
    )
    context["sectionHighlights"] = unique_keep(
        [clean_text(item, limit=140) for item in context["sectionHighlights"] if clean_text(item)],
        limit=10,
    )
    context["summary"] = summarize(context) or "暂无自动摘要"
    context["pages"] = context["pages"][:20]
    context["pageCount"] = len(context["pages"])
    context["usefulItemCount"] = len(context["items"])
    context["errors"] = unique_keep(context["errors"], limit=20)
    return context


def dumps(items):
    return json.dumps(items, ensure_ascii=False, indent=2)
