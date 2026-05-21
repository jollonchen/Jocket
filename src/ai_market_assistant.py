from __future__ import annotations

import os
import importlib.util
import re
import sys
import types
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from .news_fetcher import NewsFetcher
from .stock_analyzer import StockAnalyzer
from .stock_lookup import build_stock_directory, resolve_stock_query


DEFAULT_MARKET_KEYWORDS = [
    "A股",
    "上证指数",
    "创业板",
    "人工智能",
    "半导体",
    "新能源",
    "机器人",
    "算力",
    "低空经济",
    "政策",
]


@dataclass
class AIMarketSettings:
    provider: str
    api_key: str
    base_url: str
    model: str
    timeout: float
    temperature: float
    max_tokens: int
    skill_dir: Path


def _load_local_env() -> None:
    env_path = Path(".env")
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and (
            key.startswith("AI_MARKET_")
            or key.startswith("GEMINI_")
            or key.startswith("GOOGLE_")
            or key.startswith("OPENAI_")
        ):
            os.environ[key] = value


def _secret_value(key: str) -> str:
    try:
        import streamlit as st

        value = st.secrets.get(key)
        return str(value or "")
    except Exception:
        return ""


def _config_value(config: dict | None, key: str, default: Any = None) -> Any:
    return ((config or {}).get("ai_market") or {}).get(key, default)


def _read_secret(*keys: str) -> str:
    for key in keys:
        value = os.getenv(key) or _secret_value(key)
        if value:
            return value
    return ""


def provider_label(provider: str) -> str:
    return {"gemini": "Gemini"}.get(provider, provider)


def resolve_ai_market_settings(config: dict | None = None, provider: str | None = None) -> AIMarketSettings:
    _load_local_env()
    provider = str(
        provider
        or os.getenv("AI_MARKET_PROVIDER")
        or _config_value(config, "default_provider", "gemini")
    ).strip().lower()
    provider = "gemini"
    api_key = _read_secret("GEMINI_API_KEY", "GOOGLE_API_KEY", "AI_MARKET_GEMINI_API_KEY")
    base_url = str(
        os.getenv("GEMINI_BASE_URL")
        or _config_value(config, "gemini_base_url", "https://generativelanguage.googleapis.com/v1beta")
    ).rstrip("/")
    model = str(os.getenv("GEMINI_MODEL") or _config_value(config, "gemini_model", "gemini-3.0-flash"))

    base_url = str(
        base_url
    ).rstrip("/")
    skill_dir = Path(str(_config_value(config, "skill_dir", "Awesome-finance-skills/skills"))).resolve()
    return AIMarketSettings(
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout=float(_config_value(config, "timeout", 45)),
        temperature=float(_config_value(config, "temperature", 0.25)),
        max_tokens=int(_config_value(config, "max_tokens", 3072)),
        skill_dir=skill_dir,
    )


class AIMarketAssistant:
    """Wrap AlphaEar-style market context and chat model providers."""

    def __init__(self, config: dict | None = None, provider: str | None = None):
        self.config = config or {}
        self.settings = resolve_ai_market_settings(config, provider=provider)

    def ready(self) -> bool:
        return bool(self.settings.api_key)

    def provider_label(self) -> str:
        return provider_label(self.settings.provider)

    def context_snapshot(self, question: str = "", keywords: list[str] | None = None) -> dict:
        keywords = [item.strip() for item in (keywords or DEFAULT_MARKET_KEYWORDS) if str(item).strip()]
        stock_context = self._fetch_stock_skill_context(question)
        news_context = self._fetch_alphaear_news_context(keywords)
        return {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "deepear": self._fetch_deepear_signals(),
            "alphaear_news": news_context,
            "alphaear_stock": stock_context,
            "project_news": self._fetch_market_news(keywords),
            "sentiment": self._infer_sentiment_context(question, news_context, stock_context),
            "skill_catalog": self._skill_catalog(),
            "agentic_frameworks": self._agentic_frameworks(),
        }

    def ask(self, question: str, history: list[dict] | None = None, keywords: list[str] | None = None) -> dict:
        if not self.ready():
            return {
                "ok": False,
                "answer": f"未检测到 {self.provider_label()} API token。请在环境变量或 Streamlit secrets 中配置后重试。",
                "context": {},
            }

        context = self.context_snapshot(question, keywords)
        messages = self._build_messages(question, history or [], context)
        try:
            answer = self._ask_gemini(messages)
            return {"ok": True, "answer": answer or "模型没有返回有效内容。", "context": context}
        except Exception as exc:
            return {
                "ok": False,
                "answer": self._format_request_error(exc),
                "context": context,
            }

    def _build_messages(self, question: str, history: list[dict], context: dict) -> list[dict]:
        system_prompt = (
            "你是项目内的智能 AI 行情助手。当前系统时间是 2026 年 5 月。\n"
            "【核心原则】数据至上，客观分析，严控幻觉。\n"
            "【关键指令：强制执行】\n"
            "1. **禁止使用预训练知识**：你的模型内部可能存有 2024 年或更早的股票价格记忆（如亨通光电 15-18 元等），这些数据在 2026 年已完全失效。你必须**彻底忽略**任何关于股价、市值、财务数值的内部记忆，仅使用下方提供的“最新行情数据”进行回答。\n"
            "2. **严禁捏造数值**：如果上下文显示“最新价：74.99”，你绝对不能说成“18.50”。如果数据缺失，请直接告知“暂无实时行情”，严禁编写任何数字。\n"
            "3. **锚定上下文**：所有分析必须基于提供的 Skill 上下文。如果上下文中的数据与你的常识不符，请以此上下文为准，因为这是 2026 年的实测数据。\n"
            "4. **回答规范**：逻辑闭环，严禁截断。确保最后一个字是标点符号。回答字数控制在 500 字以内，结论先行。"
        )
        context_text = (
            f"上下文生成时间：{context.get('generated_at')}\n\n"
            f"已加载 Skill 清单：\n{context.get('skill_catalog')}\n\n"
            f"Agentic 分析框架：\n{context.get('agentic_frameworks')}\n\n"
            f"DeepEar Lite 信号：\n{context.get('deepear')}\n\n"
            f"AlphaEar News 实时热点/预测市场：\n{context.get('alphaear_news')}\n\n"
            f"AlphaEar Stock 个股行情/基本面：\n{context.get('alphaear_stock')}\n\n"
            f"项目公开新闻补充：\n{context.get('project_news')}\n\n"
            f"情绪初判：\n{context.get('sentiment')}\n"
        )
        clean_history = [
            {"role": item.get("role", "user"), "content": str(item.get("content", ""))[:2400]}
            for item in history[-8:]
            if item.get("role") in {"user", "assistant"} and item.get("content")
        ]
        return [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": context_text[:12000]},
            *clean_history,
            {"role": "user", "content": question},
        ]

    def _ask_gemini(self, messages: list[dict]) -> str:
        import time
        system_parts = [item["content"] for item in messages if item.get("role") == "system"]
        conversation = []
        for item in messages:
            role = item.get("role")
            if role == "system":
                continue
            conversation.append(
                {
                    "role": "model" if role == "assistant" else "user",
                    "parts": [{"text": str(item.get("content", ""))}],
                }
            )

        max_retries = 3
        last_err = None
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    f"{self.settings.base_url}/models/{self.settings.model}:generateContent",
                    headers={
                        "Content-Type": "application/json",
                        "x-goog-api-key": self.settings.api_key,
                    },
                    json={
                        "system_instruction": {"parts": [{"text": "\n\n".join(system_parts)}]},
                        "contents": conversation,
                        "generationConfig": {
                            "temperature": self.settings.temperature,
                            "maxOutputTokens": self.settings.max_tokens,
                        },
                    },
                    timeout=self.settings.timeout,
                )
                response.raise_for_status()
                payload = response.json()
                parts = payload.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                return "".join(str(part.get("text", "")) for part in parts)
            except Exception as e:
                last_err = e
                if attempt < max_retries - 1:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise last_err


    def _rule_stock_one_liner(self, code: str, name: str, score: dict) -> str:
        short_score = float(score.get("short_score") or 0)
        long_score = float(score.get("long_score") or 0)
        rating = str(score.get("rating") or "")
        latest = score.get("latest", {}) or {}
        ret_1d = float(latest.get("ret_1d") or 0) * 100
        if short_score >= 75 and long_score >= 70:
            label = "偏强观察"
            action = "可纳入观察池，等待回踩或量能确认。"
        elif "暂不优先" in rating or short_score < 50:
            label = "暂不优先"
            action = "短线结构偏弱，当前不宜追入。"
        elif long_score >= 70 and short_score < 60:
            label = "基本面较强，短线暂不追入"
            action = "中长线条件较好，但价格结构仍需改善。"
        else:
            label = "谨慎观察"
            action = "信号尚未充分共振，先跟踪关键价量变化。"
        return f"【{label}】{name}（{code}）今日涨跌幅{ret_1d:+.2f}%，短线{short_score:.1f}、中长线{long_score:.1f}，{action}"

    def generate_stock_one_liner(self, code: str, name: str, score: dict, hist: pd.DataFrame, fundamental_context: dict | None = None) -> str:
        if not self.ready():
            return self._rule_stock_one_liner(code, name, score)
            
        latest_price = score.get("latest", {}).get("close", 0)
        ret_1d = score.get("latest", {}).get("ret_1d", 0) * 100
        short_score = score.get("short_score", 0)
        long_score = score.get("long_score", 0)
        rating = score.get("rating", "未评级")
        rating_explanation = score.get("rating_explanation", "")
        risk_flags = "；".join(score.get("risk_flags", [])[:2])
        news = score.get("news", {}) or {}
        news_summary = news.get("summary") or "暂无高相关公开消息"
        top_news = (news.get("items") or [{}])[0]
        profile = ((fundamental_context or {}).get("payload", {}) or {}).get("profile", {}) or {}
        valuation = ((fundamental_context or {}).get("valuation", {}) or {})
        metrics = valuation.get("metrics", {}) or {}
        ratings = valuation.get("ratings", {}) or {}
        business = str(profile.get("business") or "")[:260]
        fundamental_line = (
            f"行业/主业：{profile.get('industry_cn') or profile.get('industry') or '暂未获取'}；"
            f"基本面评分：{ratings.get('overall', 'N/A')}/5；"
            f"ROE：{metrics.get('roe', 'N/A')}；PE：{metrics.get('pe_ttm', 'N/A')}；PB：{metrics.get('pb', 'N/A')}。"
        )
        
        prompt = (
            f"请用一句话总结 {name}（{code}）的今日行情并给出明确研究评级，句首用方括号评级。\n"
            f"价格与评分：最新价 {latest_price:.2f}，今日涨跌幅 {ret_1d:.2f}%，短线 {short_score:.1f}/100，中长线 {long_score:.1f}/100，系统评级：{rating}。\n"
            f"系统解释：{rating_explanation}\n"
            f"基本面：{fundamental_line}\n"
            f"主营摘要：{business or '暂无'}\n"
            f"新闻摘要：{news_summary[:220]}；最高相关消息：{top_news.get('title', '暂无')}。\n"
            f"风险：{risk_flags or '暂无显著模型内风险'}。\n\n"
            "分析要求：\n"
            "1. 必须综合技术、基本面、新闻和风险，不要只看涨跌幅。\n"
            "2. 不要输出含糊的等待类结论，要给明确结果，例如“偏强观察”“基本面较强，短线暂不追入”“暂不优先”。\n"
            "3. 80字以内，结论完整，以句号结尾。"
        )
        try:
            return self._ask_gemini([
                {"role": "system", "content": "你是A股投研助手，只基于用户提供的数据做一句话研究评级，不调用外部知识，不输出含糊结论。"},
                {"role": "user", "content": prompt}
            ])
        except Exception:
            return self._rule_stock_one_liner(code, name, score)

    def _format_request_error(self, exc: Exception) -> str:
        response = getattr(exc, "response", None)
        if response is None:
            return f"AI 行情请求失败：{exc}"
        try:
            payload = response.json()
            error = payload.get("error", payload)
        except Exception:
            error = {}
        code = error.get("code") if isinstance(error, dict) else None
        message = error.get("message") if isinstance(error, dict) else ""
        if self.settings.provider == "gemini" and response.status_code == 404:
            return f"Gemini 请求失败：当前模型 `{self.settings.model}` 不可用。请在 `.env` 或 `config.yaml` 中换成可用模型。"
        detail = message or str(exc)
        return f"{self.provider_label()} 请求失败：{detail}"

    def _fetch_deepear_signals(self) -> str:
        skill_script = self.settings.skill_dir / "alphaear-deepear-lite" / "scripts" / "deepear_lite.py"
        if skill_script.exists():
            try:
                spec = importlib.util.spec_from_file_location("alphaear_deepear_lite", skill_script)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    return module.DeepEarLiteTools().fetch_latest_signals()
            except Exception:
                pass

        url = "https://deepear.vercel.app/latest.json"
        try:
            response = requests.get(
                url,
                headers={
                    "User-Agent": "stock-picker-ui AlphaEar integration",
                    "Referer": "https://deepear.vercel.app/lite",
                },
                timeout=12,
            )
            response.raise_for_status()
            payload = response.json()
            signals = payload.get("signals", [])[:8]
            if not signals:
                return "DeepEar Lite 暂无可用信号。"
            lines = [f"Updated: {payload.get('generated_at', '-')}\n"]
            for idx, signal in enumerate(signals, 1):
                lines.append(
                    "\n".join(
                        [
                            f"{idx}. {signal.get('title', 'No Title')}",
                            f"情绪/置信/强度：{signal.get('sentiment_score', 0)} / {signal.get('confidence', 0)} / {signal.get('intensity', 0)}",
                            f"摘要：{signal.get('summary', '')}",
                            f"推理：{signal.get('reasoning', '')}",
                        ]
                    )
                )
            return "\n\n".join(lines)
        except Exception as exc:
            return f"DeepEar Lite 信号获取失败：{exc}"

    def _fetch_market_news(self, keywords: list[str]) -> str:
        try:
            payload = NewsFetcher(self.config).fetch_topics(keywords, label="AI行情实时热点", max_items=10)
            if not payload.get("available"):
                return payload.get("summary") or "暂未获取到匹配热点新闻。"
            lines = [
                f"来源：{payload.get('source', '-')}",
                f"热度：{payload.get('heat_score', '-')}",
                f"摘要：{payload.get('summary', '-')}",
            ]
            for idx, item in enumerate(payload.get("items", [])[:10], 1):
                title = item.get("title") or item.get("content") or "未命名消息"
                reason = item.get("relevance_reason") or item.get("kind") or ""
                date = item.get("date") or ""
                lines.append(f"{idx}. {title} | {date} | {reason}")
            return "\n".join(lines)
        except Exception as exc:
            return f"热点新闻获取失败：{exc}"

    def _load_skill_module(self, skill_name: str, module_name: str):
        root = self.settings.skill_dir / skill_name
        scripts_dir = root / "scripts"
        module_path = scripts_dir / f"{module_name}.py"
        if not module_path.exists():
            raise FileNotFoundError(str(module_path))

        package_name = f"awesome_{skill_name.replace('-', '_')}"
        scripts_package_name = f"{package_name}.scripts"
        if package_name not in sys.modules:
            pkg = types.ModuleType(package_name)
            pkg.__path__ = [str(root)]
            sys.modules[package_name] = pkg
        if scripts_package_name not in sys.modules:
            scripts_pkg = types.ModuleType(scripts_package_name)
            scripts_pkg.__path__ = [str(scripts_dir)]
            sys.modules[scripts_package_name] = scripts_pkg

        full_name = f"{scripts_package_name}.{module_name}"
        if full_name in sys.modules:
            return sys.modules[full_name]
        spec = importlib.util.spec_from_file_location(full_name, module_path)
        if not spec or not spec.loader:
            raise ImportError(f"Cannot load {module_path}")
        module = importlib.util.module_from_spec(spec)
        module.__package__ = scripts_package_name
        sys.modules[full_name] = module
        spec.loader.exec_module(module)
        return module

    def _fetch_alphaear_news_context(self, keywords: list[str]) -> str:
        try:
            db_mod = self._load_skill_module("alphaear-news", "database_manager")
            news_mod = self._load_skill_module("alphaear-news", "news_tools")
            db = db_mod.DatabaseManager("data/alphaear_ai_market.db")
            news_tools = news_mod.NewsNowTools(db)
            polymarket_tools = news_mod.PolymarketTools(db)
            sources = ["cls", "wallstreetcn", "xueqiu", "weibo"]
            report = news_tools.get_unified_trends(sources)
            markets = polymarket_tools.get_market_summary(limit=5)
            db.close()
            return f"{report}\n\n{markets}"
        except Exception as exc:
            fallback = self._fetch_market_news(keywords)
            return f"alphaear-news 执行失败，使用项目新闻补充：{exc}\n\n{fallback}"

    def _extract_stock_queries(self, question: str) -> list[dict]:
        results: list[dict] = []
        # Support A-share (6 digits) and HK (5 digits)
        for code in re.findall(r"\b\d{5,6}\b", question or ""):
            results.append({"code": code, "name": code})
        # Support US tickers (all caps letters)
        for ticker in re.findall(r"\b[A-Z]{2,5}\b", question or ""):
            if ticker not in DEFAULT_MARKET_KEYWORDS:
                results.append({"code": ticker, "name": ticker})
        try:
            directory = build_stock_directory()
            for item in resolve_stock_query(question, directory)[:3]:
                code = str(item.get("code") or "").strip()
                name = str(item.get("name") or "").strip()
                if code:
                    results.append({"code": code, "name": name or code})
        except Exception:
            pass
        deduped = {}
        for item in results:
            deduped[item["code"]] = item
        return list(deduped.values())[:3]

    def _fetch_stock_skill_context(self, question: str) -> str:
        stocks = self._extract_stock_queries(question)
        if not stocks:
            return "用户问题未明确匹配到个股代码/名称；本轮以市场、板块、新闻和 DeepEar 信号为主。"

        reports = []
        # Force nominal price (no adjustment) for AI reports to match user expectation
        nominal_config = self.config.copy()
        nominal_config['adjust'] = '' # Empty string means nominal in many interfaces

        for stock in stocks:
            code = stock["code"]
            name = stock.get("name", code)
            start_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
            
            try:
                # Use nominal prices for the analysis basis
                score, hist, _ = StockAnalyzer(nominal_config).analyze(code, name=name, start=start_date)
                if hist is None or hist.empty:
                    reports.append(f"## {name}（{code}）\n【❌数据缺失】未获取到该股的实时或历史行情数据。")
                    continue
                
                latest = hist.iloc[-1]
                first = hist.iloc[0]
                close = float(latest.get("close", 0) or 0)
                start_close = float(first.get("close", 0) or 0)
                change = (close / start_close - 1) * 100 if start_close else 0
                ret_1d = float(score.get("latest", {}).get("ret_1d", 0) or 0) * 100
                amount = float(latest.get("amount", 0) or 0)
                turnover = float(latest.get("turnover_rate", 0) or 0)
                latest_date = latest.get("date", "").strftime("%Y-%m-%d") if hasattr(latest.get("date"), "strftime") else str(latest.get("date", ""))
                
                # Check for stale data
                days_diff = (datetime.now() - pd.to_datetime(latest_date)).days
                is_stale = days_diff > 3

                # Fetch skill fundamentals
                skill_fundamentals = "暂无"
                try:
                    db_mod = self._load_skill_module("alphaear-stock", "database_manager")
                    stock_mod = self._load_skill_module("alphaear-stock", "stock_tools")
                    db = db_mod.DatabaseManager("data/alphaear_ai_market.db")
                    tools = stock_mod.StockTools(db, auto_update=False)
                    skill_fundamentals = tools.get_stock_fundamentals(code)
                    db.close()
                except Exception:
                    pass

                # Include more columns in the tail to prevent AI from hallucinating volume/turnover
                cols = ["date", "close", "volume"]
                if "amount" in hist.columns: cols.append("amount")
                if "turnover_rate" in hist.columns: cols.append("turnover_rate")
                
                tail = hist.tail(6)[cols].copy()
                tail_str = tail.to_string(index=False)

                integrity_warning = "【⚠️数据警告：行情已过期超过3天】" if is_stale else ""
                
                reports.append(
                    "\n".join(
                        [
                            f"## {name}（{code}）",
                            f"【✅2026年实测行情数据 - 绝对真实 - 严禁忽略】",
                            f"数据状态：{'最新' if not is_stale else '失效/过期'} {integrity_warning}",
                            f"- 数据来源：项目实时行情接口 (akshare/efinance/yfinance)",
                            f"- 交易日期：{latest_date}",
                            f"- 最新价(不复权)：{close:.2f} (此为2026年5月真实价格，忽略你记忆中的旧价格)",
                            f"- 当日涨跌：{ret_1d:+.2f}%",
                            f"- 成交额：{amount/1e8:.2f} 亿元",
                            f"- 换手率：{turnover:.2f}%",
                            f"- 区间涨跌(90d)：{change:+.2f}%",
                            f"- 基本面：{skill_fundamentals}",
                            f"- 技术分析简报：{score.get('summary', '')}",
                            "最近行情流水数据（请务必基于此数据分析，禁止编造）：",
                            tail_str,
                        ]
                    )
                )
            except Exception as exc:
                reports.append(f"## {name}（{code}）\n【❌获取失败】原因：{exc}")
        
        return "\n\n".join(reports)

    def _fetch_project_stock_fallback(self, code: str, name: str, start_date: str) -> str:
        try:
            score, hist, _ = StockAnalyzer(self.config).analyze(code, name=name, start=start_date)
            if hist is None or hist.empty:
                return "- 项目行情兜底也未返回价格序列。"
            latest = hist.iloc[-1]
            first = hist.iloc[0]
            close = float(latest.get("close", 0) or 0)
            start_close = float(first.get("close", 0) or 0)
            change = (close / start_close - 1) * 100 if start_close else 0
            latest_date = latest.get("date", "")
            ret_1d = float(score.get("latest", {}).get("ret_1d", 0) or 0) * 100
            return "\n".join(
                [
                    "- 项目实时行情兜底：已获取价格/技术评分。",
                    f"- 最新交易日：{latest_date}",
                    f"- 最新收盘：{close:.2f}",
                    f"- 区间涨跌：{change:+.2f}%",
                    f"- 当日涨跌：{ret_1d:+.2f}%",
                    f"- 短线评分：{score.get('short_score', 'N/A')}",
                    f"- 中长线评分：{score.get('long_score', 'N/A')}",
                    f"- 模型摘要：{score.get('summary', '')}",
                ]
            )
        except Exception as exc:
            return f"- 项目行情兜底失败：{exc}"

    def _infer_sentiment_context(self, question: str, news_context: str, stock_context: str) -> str:
        text = f"{question}\n{news_context[:3000]}\n{stock_context[:2000]}"
        positives = ["上涨", "增长", "利好", "突破", "强势", "景气", "中标", "订单", "政策支持", "放量"]
        negatives = ["下跌", "亏损", "利空", "减持", "处罚", "问询", "风险", "回落", "承压", "破位"]
        pos = sum(text.count(word) for word in positives)
        neg = sum(text.count(word) for word in negatives)
        if pos > neg + 2:
            label = "positive"
            score = min(0.85, 0.15 + (pos - neg) * 0.08)
        elif neg > pos + 2:
            label = "negative"
            score = max(-0.85, -0.15 - (neg - pos) * 0.08)
        else:
            label = "neutral"
            score = 0.0
        return (
            f"alphaear-sentiment 框架初判：{label}，score={score:.2f}。"
            "该分数基于新闻/行情关键词快速估计，最终情绪请由 Gemini 结合全文重新判断。"
        )

    def _skill_catalog(self) -> str:
        rows = []
        for path in sorted(self.settings.skill_dir.glob("*/SKILL.md")):
            name = path.parent.name
            text = path.read_text(encoding="utf-8", errors="ignore")
            desc = ""
            for line in text.splitlines():
                if line.startswith("description:"):
                    desc = line.split(":", 1)[1].strip()
                    break
            rows.append(f"- {name}: {desc}")
        return "\n".join(rows)

    def _agentic_frameworks(self) -> str:
        frameworks = []
        for name in (
            "alphaear-signal-tracker",
            "alphaear-predictor",
            "alphaear-reporter",
            "alphaear-logic-visualizer",
            "alphaear-search",
            "alphaear-sentiment",
        ):
            path = self.settings.skill_dir / name / "SKILL.md"
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            body = re.sub(r"---.*?---", "", text, flags=re.S).strip()
            frameworks.append(f"[{name}]\n{body[:900]}")
        return "\n\n".join(frameworks)
