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
        return "低优先级观察"
    return "暂不优先"


class FundamentalAnalyzer:
    """Generate natural-language fundamental summaries without inventing missing data."""

    def analyze(self, payload: dict, valuation: dict, technical_score: dict | None = None) -> dict:
        annual = payload.get("annual", pd.DataFrame())
        metrics = valuation.get("metrics", {})
        ratings = valuation.get("ratings", {})
        scores = ratings.get("scores", {})
        category_scores = ratings.get("category_scores", {})
        overall = ratings.get("overall")
        profile = payload.get("profile", {})

        quality_cards = self._quality_cards(annual, metrics)
        high = [name for name, score in scores.items() if score is not None and score >= 4]
        low = [name for name, score in scores.items() if score is not None and score <= 2]
        missing = [name for name, score in scores.items() if score is None]

        valuation_text = self._valuation_text(metrics, scores)
        raw_limitations = valuation.get("limitations", []) or []
        limitations = [item for item in raw_limitations if not isinstance(item, dict) and "Expecting value" not in str(item)]
        debug_errors = [item for item in raw_limitations if isinstance(item, dict) or "Expecting value" in str(item)]
        if missing:
            limitations.append("缺失评分维度：" + "、".join(missing))
        if ratings.get("coverage", 1) < 0.5:
            limitations.append("可用指标覆盖率低于 50%，评级标记为数据受限")

        explanation = self._fundamental_explanation(ratings.get("rating"), high, low, valuation_text, limitations)
        research_view = self._research_view(technical_score or {}, overall)

        return {
            "profile_summary": self._profile_summary(profile),
            "quality_cards": quality_cards,
            "valuation_explanation": valuation_text,
            "fundamental_explanation": explanation,
            "supporting_factors": high[:5],
            "dragging_factors": low[:5],
            "category_scores": category_scores,
            "research_view": research_view,
            "fundamental_decision": _rating_label(overall),
            "limitations": list(dict.fromkeys(limitations)),
            "debug_errors": debug_errors,
        }

    def _profile_summary(self, profile: dict) -> str:
        name = profile.get("name") or profile.get("code") or "该股票"
        industry = profile.get("industry") or "暂未获取"
        market = profile.get("market") or "暂未获取"
        return f"{name} 所属市场为 {market}，行业为 {industry}。公司画像会按可获取字段展示。"

    def _quality_cards(self, annual: pd.DataFrame, metrics: dict) -> list[dict]:
        def _pct_str(val):
            if val is None: return "N/A"
            return f"+{val*100:.1f}%" if val > 0 else f"{val*100:.1f}%"

        def _num_str(val, suffix=""):
            if val is None: return "N/A"
            return f"{val:.2f}{suffix}"

        revenue_growth = _growth(annual, "totalRevenue")
        profit_growth = _growth(annual, "netIncome")
        roe = metrics.get("roe")
        debt_to_equity = metrics.get("debt_to_equity")
        ocf = _latest(annual, "operatingCashFlow")
        net_income = _latest(annual, "netIncome")
        dividend_yield = metrics.get("dividend_yield")
        pe = metrics.get("pe_ttm")
        pb = metrics.get("pb")

        cards = []

        # 1. 营收增长 (YoY)
        if revenue_growth is None:
            cards.append({"label": "营业收入 (YoY)", "title": "N/A", "body": "历史收入序列暂不完整，无法计算可比增速。", "tone": "orange", "badge": "数据不足"})
        elif revenue_growth >= 0.10:
            cards.append({"label": "营业收入 (YoY)", "title": _pct_str(revenue_growth), "body": "最近一期收入同比增长较快，处于扩张趋势。", "tone": "green", "badge": "高成长"})
        elif revenue_growth >= 0:
            cards.append({"label": "营业收入 (YoY)", "title": _pct_str(revenue_growth), "body": "最近一期收入保持正增长，规模扩张较为平稳。", "tone": "cyan", "badge": "稳健"})
        else:
            cards.append({"label": "营业收入 (YoY)", "title": _pct_str(revenue_growth), "body": "最近一期收入同比下滑，需关注行业景气度。", "tone": "orange", "badge": "萎缩"})

        # 2. 净利润增长 (YoY)
        if profit_growth is None:
            cards.append({"label": "净利润 (YoY)", "title": "N/A", "body": "净利润序列暂不完整或基数为负，无法计算增速。", "tone": "orange", "badge": "数据不足"})
        elif profit_growth >= 0.15:
            cards.append({"label": "净利润 (YoY)", "title": _pct_str(profit_growth), "body": "利润端增长强劲，增速表现优异。", "tone": "green", "badge": "高爆发"})
        elif profit_growth >= 0:
            cards.append({"label": "净利润 (YoY)", "title": _pct_str(profit_growth), "body": "利润端保持稳定增长。", "tone": "cyan", "badge": "平稳"})
        else:
            cards.append({"label": "净利润 (YoY)", "title": _pct_str(profit_growth), "body": "利润端出现负增长，需排查非经常性损益或成本压力。", "tone": "red", "badge": "承压"})

        # 3. ROE
        if roe is None:
            cards.append({"label": "净资产收益率 (ROE)", "title": "N/A", "body": "暂无 ROE 数据，无法评估资本回报率。", "tone": "orange", "badge": "数据不足"})
        elif roe >= 0.15:
            cards.append({"label": "净资产收益率 (ROE)", "title": _pct_str(roe), "body": "股东权益回报表现优异，具备较强盈利壁垒。", "tone": "green", "badge": "高回报"})
        elif roe >= 0.08:
            cards.append({"label": "净资产收益率 (ROE)", "title": _pct_str(roe), "body": "盈利能力中等，处于行业常规水平。", "tone": "cyan", "badge": "合格"})
        else:
            cards.append({"label": "净资产收益率 (ROE)", "title": _pct_str(roe), "body": "权益资本回报偏低，盈利能力不突出。", "tone": "orange", "badge": "低效"})

        # 4. 现金流覆盖度
        if ocf is None or net_income is None:
            cards.append({"label": "现金流净利比", "title": "N/A", "body": "现金流或利润数据缺失。", "tone": "orange", "badge": "数据不足"})
        elif net_income > 0:
            ratio = ocf / net_income
            if ratio >= 1:
                cards.append({"label": "现金流净利比", "title": f"{ratio:.2f}x", "body": "经营现金流完全覆盖净利润，利润含金量高。", "tone": "green", "badge": "充沛"})
            elif ratio > 0:
                cards.append({"label": "现金流净利比", "title": f"{ratio:.2f}x", "body": "现金流为正但未完全覆盖净利润，需关注应收账款。", "tone": "orange", "badge": "弱覆盖"})
            else:
                cards.append({"label": "现金流净利比", "title": f"{ratio:.2f}x", "body": "经营现金流为负，纸面富贵风险较高。", "tone": "red", "badge": "失血"})
        else:
            cards.append({"label": "现金流净利比", "title": "亏损", "body": "当期净利润为负，不适用现金流覆盖度分析。", "tone": "red", "badge": "亏损"})

        # 5. D/E
        if debt_to_equity is None:
            cards.append({"label": "资产负债率 (D/E)", "title": "N/A", "body": "暂无负债权益比数据。", "tone": "orange", "badge": "数据不足"})
        elif debt_to_equity < 1:
            cards.append({"label": "资产负债率 (D/E)", "title": _num_str(debt_to_equity, "x"), "body": "自有资本充足，长期偿债压力较小。", "tone": "green", "badge": "健康"})
        elif debt_to_equity < 2.5:
            cards.append({"label": "资产负债率 (D/E)", "title": _num_str(debt_to_equity, "x"), "body": "杠杆水平适中，需结合行业重资产属性判断。", "tone": "cyan", "badge": "适中"})
        else:
            cards.append({"label": "资产负债率 (D/E)", "title": _num_str(debt_to_equity, "x"), "body": "杠杆率偏高，财务结构具备一定脆弱性。", "tone": "orange", "badge": "高杠杆"})

        # 6. 分红率
        if dividend_yield is None:
            cards.append({"label": "股息率 (TTM)", "title": "N/A", "body": "暂未获取分红或股息率数据。", "tone": "orange", "badge": "无分红"})
        elif dividend_yield >= 0.03:
            cards.append({"label": "股息率 (TTM)", "title": _pct_str(dividend_yield), "body": "股息回报具备较好吸引力，提供安全边际。", "tone": "green", "badge": "高股息"})
        elif dividend_yield > 0:
            cards.append({"label": "股息率 (TTM)", "title": _pct_str(dividend_yield), "body": "存在一定分红回报，但股息率并不突出。", "tone": "cyan", "badge": "有分红"})
        else:
            cards.append({"label": "股息率 (TTM)", "title": "0.0%", "body": "近期未见分红记录，投资收益完全依赖资本利得。", "tone": "orange", "badge": "铁公鸡"})

        # 7. PE TTM
        pe_val = _num(pe)
        if pe_val is None:
            cards.append({"label": "滚动市盈率 (PE)", "title": "N/A", "body": "估值数据缺失或当前盈利为负。", "tone": "orange", "badge": "数据不足"})
        elif pe_val <= 0:
            cards.append({"label": "滚动市盈率 (PE)", "title": "亏损", "body": "处于亏损状态，PE 估值法失效。", "tone": "red", "badge": "不适用"})
        elif pe_val < 15:
            cards.append({"label": "滚动市盈率 (PE)", "title": _num_str(pe_val, "x"), "body": "静态市盈率较低，估值可能具备安全边际。", "tone": "green", "badge": "低估值"})
        elif pe_val < 40:
            cards.append({"label": "滚动市盈率 (PE)", "title": _num_str(pe_val, "x"), "body": "市盈率处于合理或中等偏高水平。", "tone": "cyan", "badge": "合理"})
        else:
            cards.append({"label": "滚动市盈率 (PE)", "title": _num_str(pe_val, "x"), "body": "市盈率较高，估值对未来高增长存在透支预期。", "tone": "orange", "badge": "高溢价"})

        # 8. PB
        pb_val = _num(pb)
        if pb_val is None:
            cards.append({"label": "市净率 (PB)", "title": "N/A", "body": "暂无 PB 估值数据。", "tone": "orange", "badge": "数据不足"})
        elif pb_val < 1:
            cards.append({"label": "市净率 (PB)", "title": _num_str(pb_val, "x"), "body": "当前股价破净，需排查资产质量风险或周期底部。", "tone": "green", "badge": "破净"})
        elif pb_val < 3:
            cards.append({"label": "市净率 (PB)", "title": _num_str(pb_val, "x"), "body": "市净率处于常规估值水准。", "tone": "cyan", "badge": "合理"})
        else:
            cards.append({"label": "市净率 (PB)", "title": _num_str(pb_val, "x"), "body": "PB 偏高，市场对公司轻资产或ROE要求极高。", "tone": "orange", "badge": "高估值"})

        return cards

    def _valuation_text(self, metrics: dict, scores: dict) -> str:
        pe = _num(metrics.get("pe_ttm"))
        pb = _num(metrics.get("pb"))
        dcf = metrics.get("dcf", {})
        parts = []
        if pe is None and pb is None:
            parts.append("PE/PB 数据缺失，估值便宜或偏贵暂无法可靠判断。")
        elif (pe is not None and pe > 80) or (pb is not None and pb > 10):
            parts.append("按通用规则 PE/PB 偏高，但仍需结合行业估值中枢验证。")
        elif (pe is not None and 8 <= pe <= 30) or (pb is not None and 0.8 <= pb <= 4):
            parts.append("PE/PB 位于较易解释的区间，估值压力相对中性。")
        else:
            parts.append("估值指标按通用规则处于中间区间，需要结合行业分位、成长性和周期位置确认。")

        if dcf.get("available"):
            discount = dcf.get("discount_pct")
            if discount is not None and discount > 0:
                parts.append("按当前简化 DCF 假设，价格低于现金流估算值，但需进行敏感性验证。")
            elif discount is not None:
                parts.append("按当前简化 DCF 假设，价格高于现金流估算值，需谨慎看待估值安全边际。")
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
