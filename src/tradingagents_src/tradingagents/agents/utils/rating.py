"""Shared 5-tier rating vocabulary and a deterministic heuristic parser.

The same five-tier scale (Buy, Overweight, Hold, Underweight, Sell) is used by:
- The Research Manager (investment plan recommendation)
- The Portfolio Manager (final position decision)
- The signal processor (rating extracted for downstream consumers)
- The memory log (rating tag stored alongside each decision entry)

Centralising it here avoids drift between those call sites.
"""

from __future__ import annotations

import re
from typing import Tuple


# Canonical, ordered 5-tier scale (most bullish to most bearish).
RATINGS_5_TIER: Tuple[str, ...] = (
    "Buy", "Overweight", "Hold", "Underweight", "Sell",
)

_RATING_SET = {r.lower() for r in RATINGS_5_TIER}

# Matches "Rating: X" / "rating - X" / "Rating: **X**" — tolerates markdown
# bold wrappers and either a colon or hyphen separator.
_RATING_LABEL_RE = re.compile(r"rating.*?[:\-][\s*]*(\w+)", re.IGNORECASE)


def parse_rating(text: str, default: str = "Hold") -> str:
    """Heuristically extract a 5-tier rating from prose text.
    Supports both English (Buy, Overweight, Hold, Underweight, Sell) and Chinese.

    Two-pass strategy:
    1. Look for prefix-based labels, e.g., "评级：卖出" or "Rating: Underweight".
    2. Fall back to the first matching rating word in the text.
    """
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

    # Clean thinker tag
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)

    # 1. Search for Rating: X or 评级: X
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

    return default
