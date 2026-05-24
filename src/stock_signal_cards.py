from __future__ import annotations

from collections import Counter
from datetime import datetime
import re
from typing import Any

import pandas as pd


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


def _money_yi(value: Any) -> str:
    num = _num(value)
    if num is None:
        return "N/A"
    if abs(num) >= 100000000:
        return f"{num / 100000000:.1f}亿"
    if abs(num) >= 10000:
        return f"{num / 10000:.1f}万"
    return f"{num:.0f}"


def _ratio(value: Any, suffix: str = "x") -> str:
    num = _num(value)
    return "N/A" if num is None else f"{num:.2f}{suffix}"


def _pct(value: Any) -> str:
    num = _num(value)
    if num is None:
        return "N/A"
    return f"{num:.2f}%"


def _date(value: Any) -> pd.Timestamp | None:
    dt = pd.to_datetime(value, errors="coerce")
    if pd.isna(dt):
        return None
    return dt


def _frame(data: Any) -> pd.DataFrame:
    if isinstance(data, pd.DataFrame):
        return data.copy()
    if isinstance(data, list):
        return pd.DataFrame(data)
    if isinstance(data, dict):
        if "data" in data and isinstance(data["data"], list):
            return pd.DataFrame(data["data"])
        return pd.DataFrame([data])
    return pd.DataFrame()


def _card(label: str, value: str, level: str, tone: str, score: float, threshold_note: str, decision_note: str, source: str, updated_at: str, group: str) -> dict:
    return {
        "label": label,
        "value": value,
        "level": level,
        "tone": tone,
        "score": round(float(score), 1),
        "threshold_note": threshold_note,
        "decision_note": decision_note,
        "source": source,
        "updated_at": updated_at,
        "group": group,
    }


def _latest_report_eps(reports: list[dict]) -> float | None:
    for row in reports or []:
        for key in ("predictNextYearEps", "predictThisYearEps", "predictNextTwoYearEps"):
            val = _num(row.get(key))
            if val and val > 0:
                return val
    return None


def _eps_forecast_value(data: Any) -> float | None:
    df = _frame(data)
    if df.empty:
        return None
    candidates = []
    for col in df.columns:
        if "均值" in str(col) or "EPS" in str(col).upper() or "每股收益" in str(col):
            candidates.append(col)
    for col in candidates:
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        if not series.empty:
            val = float(series.iloc[-1])
            if val > 0:
                return val
    for value in df.astype(str).values.flatten():
        val = _num(value)
        if val and 0 < val < 200:
            return val
    return None


def _row_value(row: dict, names: tuple[str, ...]) -> Any:
    lowered = {str(k).lower(): v for k, v in row.items()}
    for name in names:
        if name in row:
            return row[name]
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def build_stock_signal_cards(bundle: dict, code: str, profile: dict | None = None, valuation_metrics: dict | None = None) -> dict:
    profile = profile or {}
    valuation_metrics = valuation_metrics or {}
    updated_at = str(bundle.get("updated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    quote = ((bundle.get("quote") or {}).get(str(code)) if isinstance(bundle.get("quote"), dict) else None) or {}
    if not quote and isinstance(bundle.get("quote"), dict):
        quote = next(iter(bundle["quote"].values()), {})

    pe = _num(quote.get("pe_ttm")) or _num(valuation_metrics.get("pe_ttm"))
    pb = _num(quote.get("pb")) or _num(valuation_metrics.get("pb"))
    market_cap_yi = _num(quote.get("market_cap_yi"))
    dividend_yield = _num(valuation_metrics.get("dividend_yield"))
    roe = _num(valuation_metrics.get("roe"))

    cards: list[dict] = []

    if pe is not None or pb is not None:
        valuation_score = 50
        reasons = []
        if pe is not None:
            if pe <= 0 or pe >= 80:
                valuation_score -= 25
                reasons.append("PE 处于异常或高压区")
            elif pe <= 30:
                valuation_score += 18
                reasons.append("PE 位于较易解释区间")
            elif pe <= 50:
                valuation_score -= 5
                reasons.append("PE 需要增长兑现支撑")
            else:
                valuation_score -= 16
                reasons.append("PE 偏高")
        if pb is not None:
            if pb <= 3:
                valuation_score += 10
                reasons.append("PB 可解释")
            elif pb >= 7:
                valuation_score -= 12
                reasons.append("PB 高估值")
        if roe is not None and pb is not None:
            if roe >= 0.15 and pb <= 5:
                valuation_score += 10
                reasons.append("ROE 对估值有支撑")
            elif roe < 0.08 and pb > 3:
                valuation_score -= 10
                reasons.append("ROE 与 PB 匹配偏弱")
        if dividend_yield and dividend_yield >= 0.03:
            valuation_score += 5
            reasons.append("股息提供安全垫")
        if valuation_score >= 70:
            level, tone = "估值较有支撑", "green"
        elif valuation_score >= 52:
            level, tone = "估值中性", "cyan"
        elif valuation_score >= 35:
            level, tone = "估值偏贵", "orange"
        else:
            level, tone = "业绩消化压力大", "red"
        cards.append(
            _card(
                "估值压力",
                f"PE {_ratio(pe)} / PB {_ratio(pb)}",
                level,
                tone,
                valuation_score,
                "PE 10-30 较易解释，50 以上要求高增长兑现；PB 需和 ROE 匹配。",
                "；".join(reasons[:3]) or "估值数据有限，结论降权。",
                "腾讯财经 + 估值引擎",
                updated_at,
                "valuation",
            )
        )

    reports = bundle.get("reports") or []
    eps = _eps_forecast_value(bundle.get("eps_forecast")) or _latest_report_eps(reports)
    price = _num(quote.get("price")) or _num(profile.get("latest_price"))
    if eps is not None and price:
        forward_pe = price / eps if eps > 0 else None
        digest_years = (pe / 30) if pe and pe > 0 else None
        if forward_pe and forward_pe <= 30:
            level, tone, score = "预期较易兑现", "green", 76
        elif forward_pe and forward_pe <= 50:
            level, tone, score = "需要增长兑现", "cyan", 58
        elif forward_pe:
            level, tone, score = "预期透支明显", "orange", 38
        else:
            level, tone, score = "预测不足", "orange", 30
        cards.append(
            _card(
                "预期兑现难度",
                f"Forward PE {_ratio(forward_pe)}",
                level,
                tone,
                score,
                "Forward PE 30 以下压力较轻，50 以上需要较强业绩增速消化。",
                f"机构 EPS 约 {eps:.2f}；研报样本 {len(reports or [])} 篇；PE 消化年限参考 {digest_years:.1f} 年。" if digest_years else f"机构 EPS 约 {eps:.2f}；研报样本 {len(reports or [])} 篇。",
                "同花顺一致预期 + 东财研报",
                updated_at,
                "valuation",
            )
        )

    flow_120 = _frame(bundle.get("fund_flow_120d"))
    flow_min = _frame(bundle.get("fund_flow_minute"))
    if not flow_120.empty or not flow_min.empty:
        recent = flow_120.tail(20) if not flow_120.empty else flow_min.tail(20)
        main = pd.to_numeric(recent.get("main_net_inflow", pd.Series(dtype=float)), errors="coerce").dropna()
        net = float(main.sum()) if not main.empty else None
        pos_days = int((main > 0).sum()) if not main.empty else 0
        ratio = pos_days / len(main) if len(main) else 0
        if net is not None and net > 0 and ratio >= 0.55:
            level, tone, score = "资金确认", "green", 78
        elif net is not None and net > 0:
            level, tone, score = "资金弱确认", "cyan", 60
        elif net is not None and ratio <= 0.35:
            level, tone, score = "流出承压", "orange", 34
        else:
            level, tone, score = "资金背离", "orange", 45
        cards.append(
            _card(
                "资金流验证",
                _money_yi(net),
                level,
                tone,
                score,
                "20 日主力净流入为正且正流入天数过半，才算资金确认。",
                f"近 20 条资金记录中正流入 {pos_days} 条，占比 {ratio:.0%}；用于验证量价趋势是否有资金承接。",
                "东财 push2/push2his",
                updated_at,
                "event",
            )
        )

    lhb = _frame(bundle.get("dragon_tiger"))
    if not lhb.empty:
        numeric_cols = [c for c in lhb.columns if "NET" in str(c).upper() or "净" in str(c)]
        net_vals = []
        for col in numeric_cols:
            net_vals.extend(pd.to_numeric(lhb[col], errors="coerce").dropna().tolist())
        net_sum = sum(net_vals) if net_vals else None
        inst_text = " ".join(map(str, lhb.head(20).values.flatten()))
        inst_hits = inst_text.count("机构")
        if net_sum and net_sum > 0 and inst_hits:
            level, tone, score = "机构确认", "green", 80
        elif net_sum and net_sum > 0:
            level, tone, score = "游资活跃", "cyan", 62
        elif len(lhb) >= 3:
            level, tone, score = "分歧较大", "orange", 42
        else:
            level, tone, score = "无有效席位信号", "orange", 30
        cards.append(
            _card(
                "龙虎榜强度",
                f"{len(lhb)}条",
                level,
                tone,
                score,
                "净买额为正且出现机构席位更有确认意义；频繁上榜但净买弱代表博弈加重。",
                f"机构相关文本命中 {inst_hits} 次，净额字段合计 {_money_yi(net_sum)}；短线资金活跃但需防分歧。",
                "东财龙虎榜",
                updated_at,
                "event",
            )
        )

    lockup = _frame(bundle.get("lockup"))
    if not lockup.empty:
        now = pd.Timestamp.now().normalize()
        future = []
        for _, row in lockup.iterrows():
            dt = _date(_row_value(row.to_dict(), ("LIFT_DATE", "解禁日期", "上市流通日期")))
            if dt is not None and 0 <= (dt.normalize() - now).days <= 90:
                future.append(row.to_dict())
        amount_keys = ("LIFT_MARKET_CAP", "LIFT_AMOUNT", "解禁市值", "实际解禁市值")
        total = 0.0
        for row in future:
            val = _num(_row_value(row, amount_keys))
            if val:
                total += val
        float_mcap = _num(quote.get("float_market_cap_yi"))
        pressure = total / float_mcap if float_mcap and total else None
        if pressure and pressure >= 0.08:
            level, tone, score = "高风险窗口", "red", 22
        elif pressure and pressure >= 0.03:
            level, tone, score = "中等扰动", "orange", 45
        else:
            level, tone, score = "低压力", "green", 72
        cards.append(
            _card(
                "解禁压力",
                f"{len(future)}项",
                level,
                tone,
                score,
                "未来 90 天解禁市值/流通市值超过 3% 需降权，超过 8% 是明显压力。",
                f"未来 90 天解禁估算 {_money_yi(total * 100000000 if total and total < 100000 else total)}；短线交易需避开供给冲击窗口。",
                "东财解禁日历",
                updated_at,
                "event",
            )
        )

    holders = _frame(bundle.get("holders"))
    if not holders.empty:
        text_cols = holders.head(3).to_dict("records")
        change = None
        for row in text_cols:
            change = _num(_row_value(row, ("HOLDER_NUM_RATIO", "HOLDER_NUM_CHANGE_RATE", "较上期变化", "股东户数环比")))
            if change is not None:
                break
        if change is not None and change <= -5:
            level, tone, score = "筹码集中", "green", 76
        elif change is not None and change >= 5:
            level, tone, score = "筹码分散", "orange", 36
        else:
            level, tone, score = "趋势不明", "cyan", 52
        cards.append(
            _card(
                "筹码集中度",
                _pct(change),
                level,
                tone,
                score,
                "股东户数环比下降通常代表筹码集中，上升则说明筹码分散压力。",
                "该指标适合辅助判断承接质量，不单独构成趋势结论。",
                "东财股东户数",
                updated_at,
                "event",
            )
        )

    margin = _frame(bundle.get("margin"))
    if not margin.empty:
        row = margin.iloc[0].to_dict()
        buy = _num(_row_value(row, ("RZ_BUY_AMT", "融资买入额", "FIN_BUY_AMT")))
        repay = _num(_row_value(row, ("RZ_REPAY_AMT", "融资偿还额", "FIN_REPAY_AMT")))
        balance = _num(_row_value(row, ("RZ_BALANCE", "融资余额", "FIN_BALANCE")))
        diff = (buy or 0) - (repay or 0) if buy is not None or repay is not None else None
        if diff and diff > 0:
            level, tone, score = "杠杆增配", "green", 68
        elif diff and diff < 0:
            level, tone, score = "杠杆退潮", "orange", 38
        else:
            level, tone, score = "中性", "cyan", 52
        cards.append(
            _card(
                "融资情绪",
                _money_yi(diff),
                level,
                tone,
                score,
                "融资买入大于偿还代表杠杆资金增配，连续退潮需降低风险偏好。",
                f"融资余额 {_money_yi(balance)}；该信号更适合验证中短期风险偏好。",
                "东财融资融券",
                updated_at,
                "event",
            )
        )

    blocks = _frame(bundle.get("block_trade"))
    if not blocks.empty:
        discount_values = []
        for _, row in blocks.head(10).iterrows():
            data = row.to_dict()
            discount = _num(_row_value(data, ("DISCOUNT_RATE", "折溢率", "折价率")))
            if discount is not None:
                discount_values.append(discount)
        avg_discount = sum(discount_values) / len(discount_values) if discount_values else None
        if avg_discount is not None and avg_discount <= -8:
            level, tone, score = "折价压力", "orange", 34
        elif avg_discount is not None and avg_discount >= 0:
            level, tone, score = "机构换手", "cyan", 58
        else:
            level, tone, score = "影响有限", "cyan", 50
        cards.append(
            _card(
                "大宗交易折溢价",
                _pct(avg_discount),
                level,
                tone,
                score,
                "大宗交易大幅折价通常压制短线预期，平价或溢价更偏中性。",
                f"近 {min(len(blocks), 10)} 条大宗交易均值；需要结合成交规模和买卖方继续验证。",
                "东财大宗交易",
                updated_at,
                "event",
            )
        )

    announcements = bundle.get("announcements") or []
    if announcements:
        risk_words = ("减持", "处罚", "问询", "立案", "风险", "解禁", "诉讼")
        positive_words = ("回购", "增持", "中标", "合同", "分红", "业绩预增", "并购", "重组")
        titles = "；".join(str(item.get("title") or "") for item in announcements[:10])
        risk_hits = sum(titles.count(word) for word in risk_words)
        pos_hits = sum(titles.count(word) for word in positive_words)
        if pos_hits > risk_hits and pos_hits:
            level, tone, score = "利好验证", "green", 72
        elif risk_hits:
            level, tone, score = "风险提示", "orange", 34
        else:
            level, tone, score = "需跟踪", "cyan", 52
        cards.append(
            _card(
                "公告事件强度",
                f"{len(announcements)}条",
                level,
                tone,
                score,
                "公告按业绩、并购、回购、减持、监管等事件词打分。",
                (announcements[0].get("title") or "最新公告暂无标题")[:90],
                "巨潮公告",
                updated_at,
                "event",
            )
        )

    hot = _frame(bundle.get("hot_reason"))
    code_text = str(code)
    matched = hot[hot.get("code", pd.Series(dtype=str)).astype(str).str.endswith(code_text[-6:])] if not hot.empty and "code" in hot.columns else pd.DataFrame()
    concepts = bundle.get("concepts") or {}
    board_text = " ".join(map(str, profile.get("belong_boards") or [])) + " " + str(concepts)
    if not hot.empty:
        reasons = " ".join(hot.get("reason", pd.Series(dtype=str)).astype(str).head(80).tolist())
        overlap = [word for word in set(board_text.replace("/", " ").replace("、", " ").split()) if len(word) >= 2 and word in reasons]
        if not matched.empty:
            level, tone, score = "题材正反馈", "green", 78
            value = matched.iloc[0].get("reason") or "命中热点"
        elif overlap:
            level, tone, score = "板块弱相关", "cyan", 56
            value = "、".join(overlap[:3])
        else:
            level, tone, score = "蹭热点风险", "orange", 34
            value = "未命中"
        cards.append(
            _card(
                "热点归因匹配",
                str(value)[:24],
                level,
                tone,
                score,
                "个股直接进入热点榜权重最高；仅板块词重合时降为弱相关。",
                "用于判断消息热度是否真正传导到该股，而不是只停留在题材背景。",
                "同花顺热点 + 百度概念",
                updated_at,
                "event",
            )
        )

    cards = sorted(cards, key=lambda x: (x.get("group") != "valuation", -float(x.get("score") or 0)))
    return {
        "cards": cards[:10],
        "valuation_cards": [c for c in cards if c.get("group") == "valuation"][:4],
        "event_cards": [c for c in cards if c.get("group") == "event"][:8],
        "details": {
            "reports": reports,
            "announcements": announcements,
            "dragon_tiger": lhb,
            "fund_flow_120d": flow_120,
            "lockup": lockup,
            "margin": margin,
            "block_trade": blocks,
            "holders": holders,
        },
    }


def build_market_signal_cards(bundle: dict) -> dict:
    updated_at = str(bundle.get("updated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    cards = []

    hot = _frame(bundle.get("hot_reason"))
    if not hot.empty:
        reasons = []
        for text in hot.get("reason", pd.Series(dtype=str)).astype(str).head(120):
            for token in text.replace("/", " ").replace("、", " ").replace(",", " ").split():
                if len(token) >= 2:
                    reasons.append(token[:12])
        top = Counter(reasons).most_common(3)
        concentration = top[0][1] / max(1, len(reasons)) if top else 0
        count = len(hot)
        if count >= 80 and concentration >= 0.08:
            level, tone, score = "主线清晰", "green", 78
        elif count >= 50:
            level, tone, score = "热点活跃", "cyan", 62
        else:
            level, tone, score = "扩散不足", "orange", 38
        cards.append(
            _card(
                "同花顺热点强度",
                f"{count}只",
                level,
                tone,
                score,
                "强势股数量越多、题材词越集中，主线越清晰。",
                "高频题材：" + "、".join(k for k, _ in top) if top else "热点题材暂不集中。",
                "同花顺热点",
                updated_at,
                "market",
            )
        )

    north = bundle.get("northbound") or {}
    if north:
        text = str(north)
        nums = [_num(x) for x in re.findall(r"-?\d+(?:\.\d+)?", text)]
        nums = [x for x in nums if x is not None]
        value = sum(nums[:4]) if nums else None
        if value and value > 0:
            level, tone, score = "外资加仓", "green", 70
        elif value and value < 0:
            level, tone, score = "外资流出", "orange", 36
        else:
            level, tone, score = "外资分歧", "cyan", 52
        cards.append(
            _card(
                "北向资金温度",
                _money_yi(value),
                level,
                tone,
                score,
                "北向净流入为正提升权重，持续流出时降低大盘风险偏好。",
                "该卡用最新沪深股通字段聚合，接口字段漂移时只作方向参考。",
                "同花顺/东财北向",
                updated_at,
                "market",
            )
        )

    daily_lhb = _frame(bundle.get("daily_dragon_tiger"))
    if not daily_lhb.empty:
        text = " ".join(map(str, daily_lhb.head(80).values.flatten()))
        inst_hits = text.count("机构")
        if len(daily_lhb) >= 80 and inst_hits >= 8:
            level, tone, score = "短线资金高活跃", "green", 78
        elif len(daily_lhb) >= 40:
            level, tone, score = "资金活跃", "cyan", 62
        else:
            level, tone, score = "活跃度一般", "orange", 42
        cards.append(
            _card(
                "全市场龙虎榜热度",
                f"{len(daily_lhb)}条",
                level,
                tone,
                score,
                "上榜数量和机构席位越多，代表短线资金参与度越高。",
                f"机构相关文本命中 {inst_hits} 次；用于观察市场风险偏好是否升温。",
                "东财全市场龙虎榜",
                updated_at,
                "market",
            )
        )

    industry = _frame(bundle.get("industry"))
    if not industry.empty:
        up_count = int((pd.to_numeric(industry.get("pct"), errors="coerce") > 0).sum()) if "pct" in industry.columns else 0
        top = industry.iloc[0].to_dict()
        top_pct = _num(top.get("pct"))
        ratio = up_count / max(1, len(industry))
        if ratio >= 0.62 and top_pct and top_pct > 2:
            level, tone, score = "主线扩散", "green", 76
        elif ratio >= 0.45:
            level, tone, score = "轮动中性", "cyan", 56
        else:
            level, tone, score = "板块退潮", "orange", 34
        cards.append(
            _card(
                "行业轮动强弱",
                str(top.get("board_name") or "-")[:16],
                level,
                tone,
                score,
                "上涨行业占比超过 60% 且龙头行业涨幅较强，才算扩散。",
                f"上涨行业 {up_count}/{len(industry)}；领涨 {top.get('board_name', '-')} {_pct(top_pct)}。",
                "东财行业板块",
                updated_at,
                "market",
            )
        )

    quotes = bundle.get("index_quotes") or {}
    if isinstance(quotes, dict) and quotes:
        rows = [row for row in quotes.values() if isinstance(row, dict)]
        pct_values = [_num(row.get("change_pct")) for row in rows]
        pct_values = [x for x in pct_values if x is not None]
        avg_pct = sum(pct_values) / len(pct_values) if pct_values else None
        if avg_pct and avg_pct >= 1:
            level, tone, score = "风险偏好升温", "green", 72
        elif avg_pct and avg_pct <= -1:
            level, tone, score = "承接偏弱", "orange", 34
        else:
            level, tone, score = "风格分歧", "cyan", 52
        cards.append(
            _card(
                "指数/ETF 风险偏好",
                _pct(avg_pct),
                level,
                tone,
                score,
                "核心指数与 ETF 平均涨跌反映大盘承接，正负 1% 是明显冷热分界。",
                "用于把题材活跃度和指数承接放在同一视角验证。",
                "腾讯指数/ETF",
                updated_at,
                "market",
            )
        )

    return {"cards": sorted(cards, key=lambda x: -float(x.get("score") or 0))[:8], "details": {"hot_reason": hot, "daily_dragon_tiger": daily_lhb, "industry": industry}}


def signal_cards_to_text(cards: list[dict], title: str = "信号卡片") -> str:
    if not cards:
        return f"{title}：暂无可用高价值信号卡片。"
    lines = [f"{title}："]
    for card in cards:
        lines.append(
            f"- {card.get('label')}：{card.get('level')}，值={card.get('value')}，评分={card.get('score')}；"
            f"阈值={card.get('threshold_note')}；含义={card.get('decision_note')}；来源={card.get('source')}。"
        )
    return "\n".join(lines)
