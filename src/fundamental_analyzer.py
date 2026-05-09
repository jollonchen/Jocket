from __future__ import annotations

import pandas as pd


def _num(value):
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _latest(df: pd.DataFrame, column: str):
    if df is None or df.empty or column not in df.columns:
        return None
    series = df[column].dropna()
    if series.empty:
        return None
    return _num(series.iloc[0])


def _growth(df: pd.DataFrame, column: str):
    if df is None or len(df) < 2 or column not in df.columns:
        return None
    current = _num(df[column].iloc[0])
    previous = _num(df[column].iloc[1])
    if current is None or previous in (None, 0):
        return None
    return current / previous - 1


def _rating_label(overall):
    value = _num(overall)
    if value is None:
        return "数据不足"
    if value >= 4.0:
        return "重点研究"
    if value >= 3.3:
        return "优先观察"
    if value >= 2.7:
        return "谨慎观察"
    if value >= 2.0:
        return "等待验证"
    return "暂不优先"


class FundamentalAnalyzer:
    """Generate natural-language fundamental summaries without inventing missing data."""

    def analyze(self, payload: dict, valuation: dict, technical_score: dict | None = None) -> dict:
        annual = payload.get("annual", pd.DataFrame())
        metrics = valuation.get("metrics", {})
        ratings = valuation.get("ratings", {})
        scores = ratings.get("scores", {})
        overall = ratings.get("overall")
        profile = payload.get("profile", {})

        quality_cards = self._quality_cards(annual, metrics)
        high = [name for name, score in scores.items() if score is not None and score >= 4]
        low = [name for name, score in scores.items() if score is not None and score <= 2]
        missing = [name for name, score in scores.items() if score is None]

        valuation_text = self._valuation_text(metrics, scores)
        limitations = valuation.get("limitations", []) or []
        if missing:
            limitations.append("缺失评分维度：" + "、".join(missing))

        explanation = self._fundamental_explanation(ratings.get("rating"), high, low, valuation_text, limitations)
        research_view = self._research_view(technical_score or {}, overall)

        return {
            "profile_summary": self._profile_summary(profile),
            "quality_cards": quality_cards,
            "valuation_explanation": valuation_text,
            "fundamental_explanation": explanation,
            "research_view": research_view,
            "fundamental_decision": _rating_label(overall),
            "limitations": list(dict.fromkeys(limitations)),
        }

    def _profile_summary(self, profile: dict) -> str:
        name = profile.get("name") or profile.get("code") or "该股票"
        industry = profile.get("industry") or "暂未获取"
        market = profile.get("market") or "暂未获取"
        return f"{name} 所属市场为 {market}，行业为 {industry}。公司画像字段来自公开数据源，缺失项会保持为暂未获取。"

    def _quality_cards(self, annual: pd.DataFrame, metrics: dict) -> list[dict]:
        revenue_growth = _growth(annual, "totalRevenue")
        profit_growth = _growth(annual, "netIncome")
        roe = metrics.get("roe")
        debt_to_equity = metrics.get("debt_to_equity")
        ocf = _latest(annual, "operatingCashFlow")
        net_income = _latest(annual, "netIncome")
        dividend_yield = metrics.get("dividend_yield")

        cards = []
        if revenue_growth is None:
            cards.append({"title": "收入增长趋势", "body": "当前数据源缺少可比收入序列，暂无法判断增长趋势。", "tone": "orange", "badge": "N/A"})
        elif revenue_growth > 0.10:
            cards.append({"title": "收入增长趋势", "body": "最近一期收入同比增长较快，收入端呈扩张迹象。", "tone": "green", "badge": "Growth"})
        elif revenue_growth >= 0:
            cards.append({"title": "收入增长趋势", "body": "最近一期收入保持正增长，但增速并不激进。", "tone": "cyan", "badge": "Stable"})
        else:
            cards.append({"title": "收入增长趋势", "body": "最近一期收入同比下滑，需要结合行业景气度进一步验证。", "tone": "orange", "badge": "Watch"})

        if net_income is None or ocf is None:
            cards.append({"title": "净利润质量", "body": "经营现金流或净利润数据缺失，暂无法判断利润含金量。", "tone": "orange", "badge": "N/A"})
        elif ocf >= net_income > 0:
            cards.append({"title": "净利润质量", "body": "经营现金流覆盖净利润，利润质量相对更扎实。", "tone": "green", "badge": "Cash"})
        elif net_income > 0:
            cards.append({"title": "净利润质量", "body": "净利润为正但现金流覆盖不足，需要关注回款和营运资本变化。", "tone": "orange", "badge": "Check"})
        else:
            cards.append({"title": "净利润质量", "body": "净利润为负或不可持续，基本面验证优先级上升。", "tone": "red", "badge": "Risk"})

        if roe is None:
            cards.append({"title": "盈利能力", "body": "ROE 数据缺失，当前数据源暂不支持完整盈利能力判断。", "tone": "orange", "badge": "N/A"})
        elif roe >= 0.15:
            cards.append({"title": "盈利能力", "body": "ROE 处于较高区间，股东权益回报表现较好。", "tone": "green", "badge": "ROE"})
        elif roe >= 0.08:
            cards.append({"title": "盈利能力", "body": "ROE 中等，盈利能力仍需结合估值和成长性判断。", "tone": "cyan", "badge": "ROE"})
        else:
            cards.append({"title": "盈利能力", "body": "ROE 偏低，说明权益资本回报暂不突出。", "tone": "orange", "badge": "ROE"})

        if debt_to_equity is None:
            cards.append({"title": "杠杆水平", "body": "负债权益比缺失，暂无法评估杠杆压力。", "tone": "orange", "badge": "N/A"})
        elif debt_to_equity < 1:
            cards.append({"title": "杠杆水平", "body": "D/E 低于 1，资产负债压力相对可控。", "tone": "green", "badge": "Debt"})
        elif debt_to_equity < 2:
            cards.append({"title": "杠杆水平", "body": "D/E 处于中等区间，需结合行业属性判断。", "tone": "cyan", "badge": "Debt"})
        else:
            cards.append({"title": "杠杆水平", "body": "D/E 较高，财务杠杆风险需要重点复核。", "tone": "orange", "badge": "Debt"})

        if dividend_yield is None:
            cards.append({"title": "分红能力", "body": "当前数据源暂未获取稳定分红或股息率数据。", "tone": "orange", "badge": "N/A"})
        elif dividend_yield >= 0.03:
            cards.append({"title": "分红能力", "body": "股息率具备一定吸引力，可作为长期研究的辅助项。", "tone": "green", "badge": "Yield"})
        else:
            cards.append({"title": "分红能力", "body": "股息率不高，当前研究重点更偏成长、盈利或估值修复。", "tone": "cyan", "badge": "Yield"})

        return cards

    def _valuation_text(self, metrics: dict, scores: dict) -> str:
        pe = _num(metrics.get("pe_ttm"))
        pb = _num(metrics.get("pb"))
        dcf = metrics.get("dcf", {})
        parts = []
        if pe is None and pb is None:
            parts.append("PE/PB 数据缺失，估值便宜或偏贵暂无法可靠判断。")
        elif (pe is not None and pe > 40) or (pb is not None and pb > 5):
            parts.append("PE 或 PB 分数偏低，可能反映估值偏高，也可能来自周期性盈利波动。")
        elif (pe is not None and 10 <= pe <= 25) or (pb is not None and 1 <= pb <= 3):
            parts.append("PE/PB 位于较易解释的区间，估值压力相对中性。")
        else:
            parts.append("估值指标需要结合盈利质量、行业周期和历史分位进一步确认。")

        if dcf.get("available"):
            discount = dcf.get("discount_pct")
            if discount is not None and discount > 0:
                parts.append("简化 DCF 显示当前价格低于现金流估算值，但该结果对增长率和折现率高度敏感。")
            elif discount is not None:
                parts.append("简化 DCF 显示当前价格高于现金流估算值，需谨慎看待估值安全边际。")
        else:
            parts.append(dcf.get("reason", "DCF 数据不足。"))
        return " ".join(parts)

    def _fundamental_explanation(self, rating: str, high: list[str], low: list[str], valuation_text: str, limitations: list[str]) -> str:
        high_text = "、".join(high) if high else "暂无显著高分项"
        low_text = "、".join(low) if low else "暂无显著拖累项"
        limit_text = "；".join(limitations[:2]) if limitations else "暂无额外限制"
        return (
            f"该股票当前基本面评级为 {rating or '数据受限'}。"
            f"支持项主要包括：{high_text}；拖累项主要包括：{low_text}。"
            f"{valuation_text} 数据限制：{limit_text}。"
        )

    def _research_view(self, technical_score: dict, fundamental_overall) -> str:
        short_score = _num(technical_score.get("short_score"))
        fundamental = _num(fundamental_overall)
        if short_score is None or fundamental is None:
            return "数据不足：技术面或基本面评分缺失，建议等待更多数据后再做研究排序。"
        short_strong = short_score >= 70
        fundamental_strong = fundamental >= 3.5
        if short_strong and fundamental_strong:
            return "综合研究观点：短线信号和基本面评级同时较强，可纳入重点研究池，但仍需验证买入位置和风险控制。"
        if short_strong and not fundamental_strong:
            return "综合研究观点：短线信号较强但基本面支撑不足，更适合短线观察，不适合作为中长期结论。"
        if not short_strong and fundamental_strong:
            return "综合研究观点：基本面相对更强，但技术面尚未确认，适合等待价格结构改善。"
        return "综合研究观点：短线和基本面暂未形成共振，当前暂不优先。"
