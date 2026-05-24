"""Manage analysis history by scanning existing log files."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _results_dir() -> Path:
    return Path.home() / ".tradingagents" / "logs"


def parse_company_name_from_json(path: Path | None, ticker: str, data: dict | None = None) -> str:
    """Parse the stock's Chinese name from report content or JSON fields.
    
    Can accept a Path to load, or direct dictionary data.
    """
    try:
        if data is None and path is not None:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        
        if data is None:
            return ""

        # 1. Direct field match
        if "company_name" in data and data["company_name"]:
            return str(data["company_name"]).strip()

        # 2. Extract from various analyst reports
        fields_to_check = [
            "sentiment_report",
            "news_report",
            "fundamentals_report",
            "market_report",
            "policy_report",
            "hot_money_report",
            "lockup_report",
        ]
        
        for field in fields_to_check:
            text = data.get(field, "")
            if not text:
                continue
            
            # Pattern 1: ticker followed by parenthesis containing name, e.g., 603629（利通电子）
            m1 = re.search(rf"{ticker}\s*[（\(]([^）\)\s]+)[）\)]", text)
            if m1:
                name = m1.group(1).strip()
                if name and not name.isdigit():
                    return name
            
            # Pattern 2: name followed by parenthesis containing ticker, e.g., 利通电子（603629）
            m2 = re.search(rf"([^#\s\d（\(]{{2,15}})\s*[（\(]{ticker}[）\)]", text)
            if m2:
                name = m2.group(1).strip()
                name = re.sub(r"^[#\s\*_\-]+", "", name)
                if name:
                    return name
    except Exception:
        pass
    return ""


# Module-level cache for get_history()
_history_cache: dict[str, list[dict[str, str]]] = {"key": "", "data": []}


def get_history() -> list[dict[str, str]]:
    """Scan saved analysis logs and return a sorted list (newest first).

    Each entry: {"ticker": "300750", "date": "2026-05-12", "path": "/abs/path/...json", "company_name": "宁德时代"}
    Uses an in-memory cache keyed by file paths to avoid re-reading JSON on every Streamlit rerun.
    """
    root = _results_dir()
    if not root.exists():
        return []

    # Build a quick fingerprint of all log files (paths only, no content reads)
    log_files = sorted(root.rglob("full_states_log_*.json"))
    cache_key = "|".join(str(f) for f in log_files)

    if _history_cache["key"] == cache_key and _history_cache["data"]:
        return _history_cache["data"]

    entries: list[dict[str, str]] = []
    for log_file in log_files:
        match = re.search(r"full_states_log_(\d{4}-\d{2}-\d{2})\.json$", log_file.name)
        if not match:
            continue
        date = match.group(1)
        ticker = log_file.parent.parent.name
        
        # Parse the stock's Chinese name dynamically from the JSON file
        company_name = parse_company_name_from_json(log_file, ticker)
        
        entries.append({
            "ticker": ticker,
            "date": date,
            "path": str(log_file),
            "company_name": company_name
        })

    entries.sort(key=lambda e: e["date"], reverse=True)

    # Update cache
    _history_cache["key"] = cache_key
    _history_cache["data"] = entries
    return entries


def load_analysis(path: str) -> dict[str, Any]:
    """Load a saved analysis JSON file."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def extract_signal(state: dict[str, Any]) -> str:
    """Extract the short signal (Buy/Overweight/Hold/Underweight/Sell) from a final state dict."""
    import re

    # 5-tier standard rating mapping
    RATING_MAP = {
        "buy": "Buy",
        "买入": "Buy",
        "强烈推荐": "Buy",
        "overweight": "Overweight",
        "增持": "Overweight",
        "hold": "Hold",
        "持有": "Hold",
        "观望": "Hold",
        "中性": "Hold",
        "underweight": "Underweight",
        "减持": "Underweight",
        "低配": "Underweight",
        "sell": "Sell",
        "卖出": "Sell",
        "清仓": "Sell",
    }

    # Try fields in priority order
    for field in (
        "investment_plan",
        "trader_investment_decision",
        "final_trade_decision",
    ):
        text = state.get(field, "")
        if not text:
            continue
        # Strip deep thinking <think> tags
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        
        # 1. Search for prefix-based labels, e.g., "评级：卖出" or "Rating: Underweight"
        patterns = [
            r"(?:评级|rating|指令|决策)\s*[:：\-—\s]\s*[*_]*([a-zA-Z\u4e00-\u9fa5]+)",
            r"最终评级是\s*[:：\-—\s]?\s*[*_]*([a-zA-Z\u4e00-\u9fa5]+)",
            r"最终评级[：:]\s*[*_]*([a-zA-Z\u4e00-\u9fa5]+)",
        ]
        for pat in patterns:
            for m in re.finditer(pat, cleaned, re.IGNORECASE):
                val = m.group(1).lower().strip()
                # Check direct or prefix matches in rating map
                for k, v in RATING_MAP.items():
                    if k in val or val in k:
                        return v
        
        # 2. General fallback search: check for standard words in the prose
        for word in re.findall(r"[a-zA-Z\u4e00-\u9fa5]+", cleaned):
            word_lower = word.lower()
            if word_lower in RATING_MAP:
                return RATING_MAP[word_lower]
                
    return "N/A"
