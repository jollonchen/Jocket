from __future__ import annotations

import copy
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from src.config import load_config
from src.fundamental_analyzer import FundamentalAnalyzer
from src.fundamental_fetcher import FundamentalFetcher
from src.news_fetcher import news_items_to_frame
from src.rotation_analyzer import RotationAnalyzer
from src.stock_analyzer import StockAnalyzer
from src.stock_lookup import build_stock_directory, resolve_stock_query
from src.stock_screener import StockScreener
from src.ui_components import (
    format_number_cn,
    format_percent,
    format_price,
    load_css,
    metric_card,
    plot_cashflow_vs_profit,
    plot_financial_revenue_profit,
    plot_kdj,
    plot_macd,
    plot_explainable_bar,
    plot_profitability,
    plot_price_trend,
    plot_price_volume_scatter,
    plot_ratings_snapshot,
    plot_risk_deductions,
    plot_rsi,
    plot_score_radar,
    plot_score_waterfall,
    plot_score_breakdown,
    plot_score_distribution,
    plot_score_scatter,
    plot_volume,
    render_company_profile,
    render_dimension_cards,
    render_evidence_table,
    render_financial_table,
    render_bento_grid,
    render_hero,
    render_insight_cards,
    render_ratings_list,
    render_recent_data_table,
    render_score_badge,
    render_section_title,
    render_valuation_metric_cards,
    render_warning_badge,
)
from src.utils import display_code
from src.valuation_engine import ValuationEngine


st.set_page_config(page_title="Jocket", page_icon=None, layout="wide", initial_sidebar_state="expanded")
load_css()

config = load_config()
provider_options = ["auto", "ths", "akshare", "yfinance"]
provider_labels = {
    "auto": "自动：AkShare优先，失败后切换",
    "ths": "同花顺",
    "akshare": "AkShare / 东方财富",
    "yfinance": "Yahoo Finance",
}


def _provider_index(value: str) -> int:
    return provider_options.index(value) if value in provider_options else provider_options.index("ths")


def _start_date_for_trading_days(days: int) -> pd.Timestamp:
    return (pd.Timestamp.now(tz="Asia/Shanghai").tz_localize(None).normalize() - pd.offsets.BDay(days))


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def _stock_directory() -> pd.DataFrame:
    return build_stock_directory()


def _latest_date(hist: pd.DataFrame | None) -> str:
    if hist is None or hist.empty or "date" not in hist.columns:
        return "-"
    return pd.to_datetime(hist["date"].iloc[-1]).strftime("%Y-%m-%d")


def _latest_source(hist: pd.DataFrame | None) -> str:
    if hist is None or hist.empty or "data_source" not in hist.columns:
        return "-"
    return str(hist["data_source"].iloc[-1])


def _tone_from_number(value, positive_good: bool = True) -> tuple[str, str]:
    try:
        num = float(value)
    except Exception:
        return "cyan", "neutral"
    if num > 0:
        return ("green" if positive_good else "red"), "up"
    if num < 0:
        return ("red" if positive_good else "green"), "down"
    return "cyan", "neutral"


def _build_insights(score: dict, hist: pd.DataFrame, warning: str | None = None) -> list[dict]:
    latest = score.get("latest", {}) or {}
    close = float(latest.get("close", 0) or 0)
    ma20 = float(latest.get("ma20", 0) or 0)
    ma60 = float(latest.get("ma60", 0) or 0)
    rsi = float(latest.get("rsi14", 0) or 0)
    vol_ratio = float(latest.get("vol_ratio_20", 0) or 0)
    ret_5d = float(latest.get("ret_5d", 0) or 0)
    ret_1d = float(latest.get("ret_1d", 0) or 0)

    if close > ma20 > ma60:
        trend_title, trend_body, trend_tone = "多头结构占优", "收盘价位于 MA20 与 MA60 上方，短线趋势保持顺向。", "green"
    elif close < ma20:
        trend_title, trend_body, trend_tone = "短线趋势承压", "收盘价低于 MA20，建议等待重新站回关键均线。", "orange"
    else:
        trend_title, trend_body, trend_tone = "趋势仍在确认", "价格处于均线带附近，方向感需要量能进一步验证。", "cyan"

    if vol_ratio >= 1.8 and ret_1d > 0:
        volume_title, volume_body, volume_tone = "放量上涨", "成交量显著高于 20 日均量，资金关注度提升。", "green"
    elif vol_ratio >= 1.8 and ret_1d <= 0:
        volume_title, volume_body, volume_tone = "高量分歧", "量能放大但价格未同步走强，需要警惕短线分歧。", "orange"
    else:
        volume_title, volume_body, volume_tone = "量能温和", "成交量未明显异常，趋势延续性依赖后续放量确认。", "cyan"

    risk_flags = [flag for flag in score.get("risk_flags", []) if "未发现明显" not in flag]
    if rsi >= 82:
        risk_title, risk_body, risk_tone = "RSI 过热", "动量指标进入高热区，追高性价比下降。", "red"
    elif ret_5d >= 0.25:
        risk_title, risk_body, risk_tone = "短线涨幅偏大", "近 5 日涨幅较快，容易出现获利盘扰动。", "orange"
    elif risk_flags:
        risk_title, risk_body, risk_tone = "存在模型风险", risk_flags[0], "orange"
    else:
        risk_title, risk_body, risk_tone = "风险信号温和", "模型未发现突出的内生风险信号，仍需控制仓位。", "green"

    source = _latest_source(hist)
    source_body = f"本次行情来自 {source}，最新锚点为 {_latest_date(hist)}。"
    if warning:
        source_body += " 自动兜底已触发，详情见诊断区。"

    return [
        {"label": "Trend Signal", "title": trend_title, "body": trend_body, "tone": trend_tone, "badge": "Trend"},
        {"label": "Volume Signal", "title": volume_title, "body": volume_body, "tone": volume_tone, "badge": "Volume"},
        {"label": "Risk Signal", "title": risk_title, "body": risk_body, "tone": risk_tone, "badge": "Risk"},
        {"label": "Data Health", "title": "数据源状态", "body": source_body, "tone": "cyan", "badge": source.upper() if source else "DATA"},
    ]


def _render_chart_card(title: str, badge: str, fig) -> None:
    with st.container(border=True):
        st.markdown(
            f'<div class="chart-title"><span>{title}</span><span class="pill pill-cyan">{badge}</span></div>',
            unsafe_allow_html=True,
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False, "responsive": True})


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_fundamental_payload(code: str, latest_price: float | None) -> dict:
    return FundamentalFetcher(config).fetch(code, latest_price=latest_price)


def _metric_value(metrics: dict, key: str, kind: str = "ratio") -> str:
    value = metrics.get(key)
    if value is None:
        return "N/A"
    if kind == "percent":
        return format_percent(value)
    if kind == "money":
        return format_number_cn(value)
    return format_price(value, 2)


def _render_dcf_card(metrics: dict, assumptions: dict) -> None:
    dcf = metrics.get("dcf", {}) or {}
    with st.container(border=True):
        st.markdown('<div class="chart-title"><span>简化 DCF 估值</span><span class="pill pill-orange">Simplified</span></div>', unsafe_allow_html=True)
        if not dcf.get("available"):
            st.warning(dcf.get("reason", "当前数据源缺少现金流数据，暂无法计算 DCF。"))
        else:
            cards = [
                metric_card("DCF 每股估值", format_price(dcf.get("intrinsic_per_share")), "基于现金流折现", "cyan", "neutral"),
                metric_card("当前价格", format_price(dcf.get("current_price")), "行情最新收盘价", "blue", "neutral"),
                metric_card("折价 / 溢价", format_percent(dcf.get("discount_pct")), "正值代表低于估算值", "green" if (dcf.get("discount_pct") or 0) > 0 else "orange", "neutral"),
                metric_card("安全边际价", format_price(dcf.get("margin_price")), "扣除安全边际后", "purple", "neutral"),
            ]
            render_bento_grid(cards)
        st.caption(
            "DCF 假设："
            f"{int(assumptions.get('years', 5))} 年高增长期，"
            f"现金流增长率 {format_percent(assumptions.get('cashflow_growth', 0.05))}，"
            f"永续增长率 {format_percent(assumptions.get('terminal_growth', 0.02))}，"
            f"折现率 {format_percent(assumptions.get('discount_rate', 0.10))}，"
            f"安全边际 {format_percent(assumptions.get('margin_of_safety', 0.20))}。"
        )
        st.info("简化 DCF 对增长率、折现率和现金流口径高度敏感，仅用于研究辅助，不构成估值结论或买卖建议。")


def _render_sector_heat_card(sector_payload: dict) -> None:
    boards = sector_payload.get("boards", pd.DataFrame()) if sector_payload else pd.DataFrame()
    summary = sector_payload.get("summary", {}) if sector_payload else {}
    with st.container(border=True):
        st.markdown('<div class="chart-title"><span>所属板块 / 概念热度</span><span class="pill pill-cyan">efinance + AkShare</span></div>', unsafe_allow_html=True)
        if boards is None or boards.empty:
            st.info("当前未获取到所属板块/概念数据，行业/题材评分会回退为价格动量代理。")
            return
        cards = [
            metric_card("最强板块", str(summary.get("top_board") or "N/A"), "所属板块中涨幅最高", "green" if (summary.get("top_board_pct") or 0) > 0 else "orange", "neutral"),
            metric_card("最强涨幅", f"{float(summary.get('top_board_pct') or 0):+.2f}%", "efinance 即时板块涨幅", "green" if (summary.get("top_board_pct") or 0) > 0 else "red", "neutral"),
            metric_card("前三均涨幅", f"{float(summary.get('avg_top3_pct') or 0):+.2f}%", "板块扩散强度", "green" if (summary.get("avg_top3_pct") or 0) > 0 else "orange", "neutral"),
            metric_card("上涨板块数", str(summary.get("positive_count") or 0), f"数据源 {summary.get('source', '-')}", "cyan", "neutral"),
        ]
        render_bento_grid(cards)
        view = boards.head(10).copy()
        rename = {
            "board_name": "板块/概念",
            "board_code": "板块代码",
            "board_pct": "板块涨幅",
            "flow_pct": "资金流板块涨幅",
            "net_flow": "资金净额",
            "leader": "领涨股",
            "source": "数据源",
        }
        keep = [col for col in ["board_name", "board_code", "board_pct", "flow_pct", "net_flow", "leader", "source"] if col in view.columns]
        view = view[keep].rename(columns=rename)
        for col in ["板块涨幅", "资金流板块涨幅"]:
            if col in view.columns:
                view[col] = pd.to_numeric(view[col], errors="coerce").map(lambda x: "N/A" if pd.isna(x) else f"{x:+.2f}%")
        if "资金净额" in view.columns:
            view["资金净额"] = pd.to_numeric(view["资金净额"], errors="coerce").map(lambda x: "N/A" if pd.isna(x) else f"{x:+.2f}")
        st.dataframe(view, hide_index=True, use_container_width=True, height=min(420, 44 + len(view) * 38))


def _render_fundamental_snapshot(code: str, hist: pd.DataFrame, score: dict, dcf_assumptions: dict) -> dict | None:
    latest_price = None
    if hist is not None and not hist.empty and "close" in hist.columns:
        latest_price = float(hist["close"].iloc[-1])

    render_section_title("公司基本面与估值快照", "Fundamental & Valuation Snapshot")
    with st.spinner("正在获取公司基本信息、财务数据和估值指标..."):
        try:
            payload = _fetch_fundamental_payload(code, latest_price)
            valuation = ValuationEngine(dcf_assumptions).analyze(payload)
            analysis = FundamentalAnalyzer().analyze(payload, valuation, score)
        except Exception as exc:
            with st.container(border=True):
                st.markdown('<div class="chart-title"><span>基本面数据获取失败</span><span class="pill pill-orange">Fallback</span></div>', unsafe_allow_html=True)
                st.warning("基本面模块没有成功生成，但行情和技术评分仍可继续使用。")
                with st.expander("Debug detail", expanded=False):
                    st.write(str(exc))
            return None

    profile = payload.get("profile", {})
    metrics = valuation.get("metrics", {})
    ratings = valuation.get("ratings", {})
    annual = payload.get("annual", pd.DataFrame())
    quarterly = payload.get("quarterly", pd.DataFrame())

    if payload.get("errors"):
        with st.container(border=True):
            st.markdown('<div class="chart-title"><span>基本面数据源诊断</span><span class="pill pill-orange">Partial</span></div>', unsafe_allow_html=True)
            st.warning("AkShare 或部分财务接口不可用时，页面会使用 yfinance 等可用数据源；缺失字段会显示为暂未获取。")
            with st.expander("Debug detail", expanded=False):
                st.write("\n".join(payload.get("errors", [])))

    render_company_profile(profile, analysis.get("profile_summary", ""))
    _render_sector_heat_card(payload.get("sector", {}))
    render_valuation_metric_cards(metrics)

    rating_col, list_col = st.columns([1.2, 0.8])
    with rating_col:
        _render_chart_card("Ratings Snapshot", "1-5 Score", plot_ratings_snapshot(ratings))
    with list_col:
        with st.container(border=True):
            st.markdown('<div class="chart-title"><span>核心财务与估值维度评分</span><span class="pill pill-cyan">Overall</span></div>', unsafe_allow_html=True)
            render_ratings_list(ratings)
            st.caption("不可得指标显示 N/A，且不纳入 Overall Score。")

    _render_dcf_card(metrics, valuation.get("assumptions", dcf_assumptions))

    render_section_title("财务趋势", "年度和季度数据分开展示；缺失字段保持为空，不使用 0 冒充数据。")
    annual_tab, quarterly_tab = st.tabs(["年度财务", "季度财务"])
    for tab, data, label in [(annual_tab, annual, "Annual"), (quarterly_tab, quarterly, "Quarterly")]:
        with tab:
            if data is None or data.empty:
                st.info("当前数据源暂未返回该周期财务数据。")
                continue
            c1, c2 = st.columns(2)
            with c1:
                _render_chart_card(f"{label} 收入与净利润", "Revenue / Profit", plot_financial_revenue_profit(data))
            with c2:
                _render_chart_card(f"{label} 盈利能力", "ROE / ROA", plot_profitability(data))
            _render_chart_card(f"{label} 现金流 vs 净利润", "Cash Flow", plot_cashflow_vs_profit(data))
            render_financial_table(data)

    render_section_title("财务质量摘要", "自动解释收入、利润质量、盈利能力、杠杆和分红能力。")
    render_insight_cards(analysis.get("quality_cards", []))

    with st.container(border=True):
        st.markdown('<div class="chart-title"><span>基本面评级解释</span><span class="pill pill-purple">Research View</span></div>', unsafe_allow_html=True)
        st.write(analysis.get("fundamental_explanation"))
        st.info(analysis.get("research_view"))
        for note in analysis.get("limitations", []):
            st.caption(f"限制：{note}")
    return {"payload": payload, "valuation": valuation, "analysis": analysis}


def _rating_tone(rating: str) -> str:
    if "重点研究" in rating or "优先观察" in rating:
        return "green"
    if "强势" in rating or "研究池" in rating:
        return "green"
    if "风险" in rating or "谨慎" in rating:
        return "orange"
    if "不优先" in rating or "回避" in rating:
        return "red"
    return "cyan"


def _num(value):
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _score_item(
    dimension: str,
    score: float,
    max_score: float,
    logic: str,
    data_points: dict,
    positive: list[str],
    negative: list[str],
    decision_impact: str,
) -> dict:
    score = round(max(0, min(max_score, score)), 1)
    return {
        "dimension": dimension,
        "score": score,
        "max_score": max_score,
        "score_rate": round(score / max_score, 3) if max_score else 0,
        "weight": round(max_score / 100, 2),
        "logic": logic,
        "data_points": data_points,
        "positive_factors": positive or ["暂无明确加分项"],
        "negative_factors": negative or ["暂无明显扣分项"],
        "decision_impact": decision_impact,
    }


def _avg_available(values: list[float | None]) -> float | None:
    usable = [float(v) for v in values if v is not None]
    if not usable:
        return None
    return sum(usable) / len(usable)


def _replace_breakdown_item(items: list[dict], old_names: set[str], new_item: dict) -> list[dict]:
    replaced = False
    out = []
    for item in items:
        if item.get("dimension") in old_names:
            if not replaced:
                out.append(new_item)
                replaced = True
        else:
            out.append(item)
    if not replaced:
        out.insert(0, new_item)
    return out


def _enrich_sector_proxy_item(score: dict, fundamental_context: dict) -> None:
    payload = fundamental_context.get("payload", {})
    profile = payload.get("profile", {})
    sector_payload = payload.get("sector", {}) or {}
    sector_summary = sector_payload.get("summary", {}) or {}
    industry = profile.get("industry") or "暂未获取"
    industry_cn = profile.get("industry_cn") or "暂未获取"
    sector = profile.get("sector") or "暂未获取"
    boards = sector_summary.get("primary_boards", []) or profile.get("belong_boards", []) or []
    top_board = sector_summary.get("top_board")
    top_pct = _num(sector_summary.get("top_board_pct"))
    avg_top3 = _num(sector_summary.get("avg_top3_pct"))
    positive_count = int(sector_summary.get("positive_count") or 0)
    net_flow_sum = _num(sector_summary.get("net_flow_sum"))
    source = sector_summary.get("source", "efinance")
    short_breakdown = score.get("short_breakdown", [])
    for item in short_breakdown:
        if item.get("dimension") != "行业/题材代理":
            continue
        if sector_summary.get("available"):
            sector_score = 0
            positives, negatives = [], []
            if top_pct is not None:
                if top_pct >= 3:
                    sector_score += 5; positives.append(f"最强所属板块 {top_board} 涨幅 {top_pct:.2f}%")
                elif top_pct >= 1:
                    sector_score += 3; positives.append(f"最强所属板块 {top_board} 涨幅为正")
                elif top_pct < 0:
                    negatives.append(f"最强所属板块 {top_board} 仍为下跌，板块强度不足")
            if avg_top3 is not None:
                if avg_top3 >= 1:
                    sector_score += 4; positives.append(f"前三所属板块平均涨幅 {avg_top3:.2f}%")
                elif avg_top3 < 0:
                    negatives.append(f"前三所属板块平均涨幅 {avg_top3:.2f}%，板块联动偏弱")
            if positive_count >= 4:
                sector_score += 3; positives.append(f"所属板块中 {positive_count} 个为上涨，扩散度较好")
            elif positive_count > 0:
                sector_score += 2; positives.append(f"所属板块中 {positive_count} 个为上涨")
            if net_flow_sum is not None:
                if net_flow_sum > 0:
                    sector_score += 3; positives.append(f"已匹配板块资金净流入合计 {net_flow_sum:.2f}")
                else:
                    negatives.append(f"已匹配板块资金净流出合计 {net_flow_sum:.2f}")
            else:
                negatives.append("AkShare 板块资金流未完全匹配或请求失败，资金流不参与本次加分")
            item["score"] = round(max(0, min(15, sector_score)), 1)
            item["score_rate"] = round(item["score"] / 15, 3)
            item["positive_factors"] = positives or ["所属板块数据已获取，但强度信号不突出"]
            item["negative_factors"] = negatives or ["暂无明显板块扣分项"]
        else:
            item["negative_factors"] = [
                "所属板块接口不可用，暂时回退为个股价格动量和成交活跃度代理。",
            ]
        data_points = item.get("data_points", {}) or {}
        data_points.update({
            "industry": industry,
            "industry_cn": industry_cn,
            "sector": sector,
            "belong_boards": "、".join(map(str, boards[:8])) if boards else None,
            "top_board": top_board,
            "top_board_pct": top_pct / 100 if top_pct is not None else None,
            "avg_top3_board_pct": avg_top3 / 100 if avg_top3 is not None else None,
            "positive_board_count": positive_count,
            "board_net_flow_sum": net_flow_sum,
            "board_source": source,
        })
        item["data_points"] = data_points
        item["logic"] = (
            "使用 efinance 获取个股所属行业/概念板块及板块涨幅，并尝试用 AkShare 匹配板块资金流；"
            "接口失败时回退为价格动量和成交活跃度代理。"
        )
        positives = list(item.get("positive_factors", []))
        if industry_cn not in {"暂未获取", "当前数据源暂不支持", ""}:
            positives.insert(0, f"已识别行业/主板块：{industry_cn}")
        elif industry not in {"暂未获取", "当前数据源暂不支持", ""}:
            positives.insert(0, f"已识别行业：{industry}")
        if sector not in {"暂未获取", "当前数据源暂不支持", ""}:
            positives.insert(1, f"已识别 Sector：{sector}")
        item["positive_factors"] = positives or item.get("positive_factors", [])
        item["decision_impact"] = (
            "该分数现在反映所属板块/概念的即时涨幅和可用资金流；新闻热度、涨停家数和更细概念强度仍需后续补充。"
        )
        break


def _build_integrated_long_items(fundamental_context: dict) -> tuple[list[dict], list[str], bool]:
    payload = fundamental_context.get("payload", {})
    valuation = fundamental_context.get("valuation", {})
    metrics = valuation.get("metrics", {})
    ratings = valuation.get("ratings", {})
    scores = ratings.get("scores", {})
    annual = payload.get("annual", pd.DataFrame())
    profile = payload.get("profile", {})
    limitations = []

    financial_available = annual is not None and not annual.empty
    available_score_count = len([v for v in scores.values() if v is not None])
    if not financial_available and available_score_count < 3:
        limitations.append("基本面数据仍不足，中长线评分保留技术趋势为主。")
        return [], limitations, False

    quality_avg = _avg_available([scores.get("ROE"), scores.get("ROA"), scores.get("D/E")])
    growth_avg = _avg_available([scores.get("Revenue Growth"), scores.get("Net Profit Growth")])
    valuation_avg = _avg_available([scores.get("P/E"), scores.get("P/B"), scores.get("Dividend Yield"), scores.get("DCF")])

    quality_score = 10 if quality_avg is None else quality_avg / 5 * 15
    growth_score = 8 if growth_avg is None else growth_avg / 5 * 15
    valuation_score = 5 if valuation_avg is None else valuation_avg / 5 * 10

    positive_quality, negative_quality = [], []
    if _num(metrics.get("roe")) is not None:
        (positive_quality if metrics["roe"] >= 0.10 else negative_quality).append(f"ROE 为 {format_percent(metrics.get('roe'))}")
    if _num(metrics.get("roa")) is not None:
        (positive_quality if metrics["roa"] >= 0.04 else negative_quality).append(f"ROA 为 {format_percent(metrics.get('roa'))}")
    if _num(metrics.get("debt_to_equity")) is not None:
        (positive_quality if metrics["debt_to_equity"] < 1 else negative_quality).append(f"D/E 为 {format_price(metrics.get('debt_to_equity'), 2)}，使用总负债/股东权益代理")
    if quality_avg is None:
        negative_quality.append("ROE、ROA、D/E 可用性不足，质量分仍偏保守")

    quality_item = _score_item(
        "财务质量",
        quality_score,
        15,
        "使用已获取的 ROE、ROA 和 D/E 评估盈利能力与杠杆水平；缺失指标不参与平均。",
        {
            "roe": metrics.get("roe"),
            "roa": metrics.get("roa"),
            "debt_to_equity": metrics.get("debt_to_equity"),
            "industry": profile.get("industry"),
            "sector": profile.get("sector"),
        },
        positive_quality,
        negative_quality,
        "财务质量分越高，说明盈利能力和杠杆结构越能支撑中长期研究；低分时应降低长期结论权重。",
    )

    positive_growth, negative_growth = [], []
    revenue_growth = scores.get("Revenue Growth")
    profit_growth = scores.get("Net Profit Growth")
    if revenue_growth is not None:
        (positive_growth if revenue_growth >= 3 else negative_growth).append(f"收入增长评分 {revenue_growth}/5")
    if profit_growth is not None:
        (positive_growth if profit_growth >= 3 else negative_growth).append(f"净利润增长评分 {profit_growth}/5")
    if growth_avg is None:
        negative_growth.append("缺少可比营收或净利润序列，成长分使用保守占位")

    growth_item = _score_item(
        "成长表现",
        growth_score,
        15,
        "使用最近可比年度的收入增长和净利润增长评分衡量成长性；缺失指标不参与平均。",
        {
            "revenue_growth_score": revenue_growth,
            "net_profit_growth_score": profit_growth,
        },
        positive_growth,
        negative_growth,
        "成长分高说明业绩趋势对中长线研究更友好；成长分低或缺失时，需要结合财报和行业景气度验证。",
    )

    positive_val, negative_val = [], []
    for key, label in [("pe_ttm", "PE TTM"), ("pb", "PB"), ("ps", "PS"), ("dividend_yield", "股息率")]:
        value = metrics.get(key)
        if value is not None:
            text = format_percent(value) if key == "dividend_yield" else format_price(value, 2)
            (positive_val if scores.get({"pe_ttm": "P/E", "pb": "P/B", "dividend_yield": "Dividend Yield"}.get(key), 3) >= 3 else negative_val).append(f"{label} 为 {text}")
    dcf = metrics.get("dcf", {})
    if dcf.get("available"):
        (positive_val if (dcf.get("discount_pct") or 0) >= -0.10 else negative_val).append(f"简化 DCF 折价/溢价 {format_percent(dcf.get('discount_pct'))}")
    else:
        negative_val.append(dcf.get("reason", "DCF 数据不足"))
    if valuation_avg is None:
        negative_val.append("PE/PB/DCF/股息率可用性不足，估值分使用保守占位")

    valuation_item = _score_item(
        "估值与股息",
        valuation_score,
        10,
        "综合 PE、PB、股息率和简化 DCF 的 1-5 分评分，转换为 10 分制；PS 作为辅助展示指标。",
        {
            "pe_ttm": metrics.get("pe_ttm"),
            "pb": metrics.get("pb"),
            "ps": metrics.get("ps"),
            "dividend_yield": metrics.get("dividend_yield"),
            "dcf_discount_pct": dcf.get("discount_pct") if dcf else None,
        },
        positive_val,
        negative_val,
        "估值分高代表当前估值压力相对可解释；低分不等于不能研究，但需要更强成长或催化支撑。",
    )

    for note in valuation.get("limitations", []):
        if "AkShare" in note or "简化 DCF" in note or "暂不支持" in note:
            limitations.append(note)
    return [quality_item, growth_item, valuation_item], list(dict.fromkeys(limitations)), True


def _rating_with_fundamentals(score: dict, fundamental_context: dict, integrated: bool) -> tuple[str, str]:
    valuation = fundamental_context.get("valuation", {})
    ratings = valuation.get("ratings", {})
    fundamental_overall = _num(ratings.get("overall"))
    short_score = _num(score.get("short_score")) or 0
    long_score = _num(score.get("long_score")) or 0
    risk_item = next((item for item in score.get("short_breakdown", []) if item.get("dimension") == "风险控制"), {})
    risk_score = _num(risk_item.get("score")) or 0

    if not integrated or fundamental_overall is None:
        if short_score >= 70:
            return "优先观察（基本面待验证）", "短线信号较强，但基本面数据不足，适合观察而不是直接形成中长期结论。"
        if short_score < 55 and long_score < 55:
            return "暂不优先（基本面待验证）", "技术信号和基本面数据均不足，当前不作为优先研究标的。"
        return "等待验证（基本面待验证）", "技术面信号尚可继续跟踪，但基本面证据不足，需要等待更多数据。"

    if short_score >= 75 and risk_score >= 10 and fundamental_overall >= 3.5:
        return "重点研究", "短线趋势、风险控制和基本面评级形成较好共振，适合纳入重点研究池，但不等于直接买入。"
    if short_score >= 70 and fundamental_overall >= 2.8:
        return "优先观察", "短线信号偏强，基本面评级不弱，适合进入观察池并等待买点和外部验证。"
    if short_score >= 70 and fundamental_overall < 2.8:
        return "短线观察，基本面待验证", "短线信号较强，但基本面评级偏弱或估值压力较大，更适合短线观察。"
    if short_score < 60 and fundamental_overall >= 3.5:
        return "等待技术确认", "基本面评级较好，但短线结构尚未确认，适合等待趋势改善。"
    if short_score < 55 and long_score < 55 and fundamental_overall < 2.8:
        return "暂不优先", "技术面和基本面暂未形成优势，当前不作为优先研究标的。"
    return "谨慎观察", "技术面和基本面信号不够一致，适合继续跟踪并等待更明确证据。"


def _enrich_score_with_fundamentals(score: dict, fundamental_context: dict | None) -> dict:
    if not fundamental_context:
        return score
    enriched = copy.deepcopy(score)
    _enrich_sector_proxy_item(enriched, fundamental_context)
    new_items, fundamental_limitations, integrated = _build_integrated_long_items(fundamental_context)
    if integrated and new_items:
        long_breakdown = enriched.get("long_breakdown", [])
        replacements = [
            ({"质量占位"}, new_items[0]),
            ({"成长占位"}, new_items[1]),
            ({"估值占位"}, new_items[2]),
        ]
        for old_names, new_item in replacements:
            long_breakdown = _replace_breakdown_item(long_breakdown, old_names, new_item)
        enriched["long_breakdown"] = long_breakdown
        enriched["long_parts"] = {item["dimension"]: item["score"] for item in long_breakdown}
        enriched["long_score"] = min(100, max(0, round(sum(enriched["long_parts"].values()), 1)))
        enriched["composite_score"] = round(float(enriched.get("short_score", 0) or 0) * 0.55 + enriched["long_score"] * 0.30 + (fundamental_context["valuation"]["ratings"].get("overall") or 0) / 5 * 15, 1)
        enriched["fundamental_integrated"] = True
    else:
        enriched["fundamental_integrated"] = False

    rating, explanation = _rating_with_fundamentals(enriched, fundamental_context, enriched["fundamental_integrated"])
    enriched["rating"] = rating
    enriched["rating_explanation"] = explanation

    base_limitations = [
        note for note in enriched.get("limitations", [])
        if "未接入完整财务数据" not in note and "质量/成长/估值为占位分" not in note
        and "若基本面模块未能返回财务/估值数据" not in note
    ]
    if enriched["fundamental_integrated"]:
        base_limitations.append("财务和估值指标已参与中长线评分；行业热度、主力资金和新闻催化仍未接入。")
    else:
        base_limitations.append("基本面数据不足，财务/成长/估值仍未完整参与评分。")
    base_limitations.extend(fundamental_limitations)
    enriched["limitations"] = list(dict.fromkeys(base_limitations + ["评分仅用于研究辅助，不构成投资建议"]))
    enriched["score_explanations"] = _score_explanations_with_context(enriched, fundamental_context)
    enriched["summary"] = f"{rating}。{explanation} 风险提示：" + "；".join(enriched.get("risk_flags", [])[:2])
    return enriched


def _score_explanations_with_context(score: dict, fundamental_context: dict) -> list[str]:
    ratings = fundamental_context.get("valuation", {}).get("ratings", {})
    overall = ratings.get("overall")
    text = [
        "短线评分仍主要来自趋势、量价、动量、流动性和技术风险控制；高分代表信号强度，不代表确定收益。",
    ]
    if score.get("fundamental_integrated"):
        text.append(f"中长线评分已把可获取的财务质量、成长表现、估值与股息纳入计算；当前基本面 Overall Score 为 {overall if overall is not None else 'N/A'} / 5。")
    else:
        text.append("中长线评分仍以价格趋势和波动代理为主，因为可用财务/估值数据不足。")
    long_items = sorted(score.get("long_breakdown", []), key=lambda x: x.get("score_rate", 0), reverse=True)
    if long_items:
        text.append("中长线贡献较大的维度：" + "、".join(f"{item['dimension']}({item['score']}/{item['max_score']})" for item in long_items[:3]))
        text.append("中长线拖累较大的维度：" + "、".join(f"{item['dimension']}({item['score']}/{item['max_score']})" for item in sorted(long_items, key=lambda x: x.get("score_rate", 0))[:3]))
    text.append("行业热度、概念强度、资金流和公告新闻尚未并入评分，因此仍需要外部信息验证。")
    return text


def _render_scoring_methodology(score: dict) -> None:
    formula = score.get("formula", {})
    with st.expander("查看评分公式", expanded=False):
        st.markdown("**短线评分区间含义**")
        st.markdown("- 85-100：短线强势，但需检查是否追高；适合优先观察，不等于直接买入。")
        st.markdown("- 70-84：短线偏强，可进入观察池，等待回踩或确认信号。")
        st.markdown("- 55-69：中性偏弱，仅适合继续跟踪，不作为优先标的。")
        st.markdown("- 40-54：短线信号不足，除非有外部催化，否则不建议优先关注。")
        st.markdown("- 0-39：短线弱势或风险较高，建议回避。")
        st.markdown("**中长线评分区间含义**")
        if score.get("fundamental_integrated"):
            st.markdown("- 当前版本：中长线评分已纳入可获取的财务质量、成长表现、估值与股息指标，同时保留长期趋势和稳定性。")
        else:
            st.markdown("- 当前版本：中长线评分以长期趋势和波动代理为主，财务/估值因数据不足暂未完整参与。")
        st.markdown("- 85-100：趋势和基本面指标较强，适合纳入中长期研究池。")
        st.markdown("- 70-84：中长期结构较好，但仍需补充财务、估值和外部信息验证。")
        st.markdown("- 55-69：中性，需要等待趋势或基本面进一步确认。")
        st.markdown("- 40-54：中长期吸引力不足。")
        st.markdown("- 0-39：中长期风险较高或数据质量不足。")
        for group_label, group in [("短线模型", formula.get("short", {})), ("中长线模型", formula.get("long", {}))]:
            st.markdown(f"**{group_label}**")
            for dimension, rules in group.items():
                st.markdown(f"- {dimension}：" + "；".join(rules))
        st.warning("评分代表信号强度，不代表确定收益；短线高分仍需结合买入位置、止损、市场环境和仓位管理。")


def _render_explainable_scoring(score: dict) -> None:
    short_breakdown = score.get("short_breakdown", [])
    long_breakdown = score.get("long_breakdown", [])
    evidence = score.get("evidence", {})
    rating = score.get("rating", "中性观察")
    rating_tone = _rating_tone(rating)
    risk_control = next((item for item in short_breakdown if item.get("dimension") == "风险控制"), {})
    risk_text = f"{format_price(risk_control.get('score'), 1)} / {format_price(risk_control.get('max_score'), 0)}"

    render_section_title("Explainable Scoring", "评分不是黑盒：每个维度都能展开查看公式、触发条件、底层数据、加分项和扣分项。")
    render_bento_grid(
        [
            metric_card("短线评分", f"{format_price(score.get('short_score'), 1)} / 100", "信号强度，不等于买入指令", "green" if score.get("short_score", 0) >= 80 else "cyan", "up" if score.get("short_score", 0) >= 70 else "neutral"),
            metric_card("中长线评分", f"{format_price(score.get('long_score'), 1)} / 100", "趋势 + 财务/成长/估值" if score.get("fundamental_integrated") else "趋势代理 + 基本面待验证", "cyan", "neutral"),
            metric_card("综合评级", rating, score.get("rating_explanation", ""), rating_tone, "neutral"),
            metric_card("风险状态", risk_text, "风险控制分越高，技术风险越低", "green" if risk_control.get("score", 0) >= 10 else "orange", "neutral"),
        ]
    )
    with st.container(border=True):
        st.markdown('<div class="chart-title"><span>评分含义说明</span><span class="pill pill-orange">Research only</span></div>', unsafe_allow_html=True)
        st.write(score.get("rating_explanation", "暂无评级解释。"))
        for line in score.get("score_explanations", []):
            st.markdown(f"- {line}")
        for note in score.get("limitations", []):
            st.caption(f"限制：{note}")

    _render_scoring_methodology(score)

    tab_short, tab_long, tab_evidence = st.tabs(["短线评分解释", "中长线评分解释", "底层数据证据"])
    with tab_short:
        c1, c2 = st.columns(2)
        with c1:
            _render_chart_card("短线维度得分 / 满分", "Bar", plot_explainable_bar(short_breakdown, "短线维度得分"))
        with c2:
            _render_chart_card("短线得分率雷达", "Radar", plot_score_radar(short_breakdown, "短线得分率"))
        c3, c4 = st.columns(2)
        with c3:
            _render_chart_card("短线贡献度", "Waterfall", plot_score_waterfall(short_breakdown, "短线贡献度"))
        with c4:
            _render_chart_card("短线扣分 / 缺口", "Risk gap", plot_risk_deductions(short_breakdown, "短线扣分 / 缺口"))
        render_dimension_cards(short_breakdown, "short")

    with tab_long:
        if score.get("fundamental_integrated"):
            st.info("中长线评分已用可获取的 ROE、ROA、D/E、收入/利润增长、PE/PB/股息率和简化 DCF 替换旧占位项；行业热度、主力资金、公告新闻仍需外部验证。")
        else:
            st.warning("中长线评分主要基于价格趋势代理，财务和估值数据不足，因此不应单独作为中长期投资依据。")
        c1, c2 = st.columns(2)
        with c1:
            _render_chart_card("中长线维度得分 / 满分", "Bar", plot_explainable_bar(long_breakdown, "中长线维度得分"))
        with c2:
            _render_chart_card("中长线得分率雷达", "Radar", plot_score_radar(long_breakdown, "中长线得分率"))
        c3, c4 = st.columns(2)
        with c3:
            _render_chart_card("中长线贡献度", "Waterfall", plot_score_waterfall(long_breakdown, "中长线贡献度"))
        with c4:
            _render_chart_card("中长线扣分 / 缺口", "Risk gap", plot_risk_deductions(long_breakdown, "中长线扣分 / 缺口"))
        render_dimension_cards(long_breakdown, "long")

    with tab_evidence:
        with st.container(border=True):
            st.markdown('<div class="chart-title"><span>底层数据证据</span><span class="pill pill-cyan">Indicators</span></div>', unsafe_allow_html=True)
            render_evidence_table(evidence)


def _render_analysis_dashboard(score: dict, hist: pd.DataFrame, report_path: str, dcf_assumptions: dict) -> None:
    latest = score.get("latest", {}) or {}
    warning = hist.attrs.get("fallback_warning")
    ret_1d = latest.get("ret_1d")
    amount = latest.get("amount_est", latest.get("amount"))
    if amount is None and latest.get("close") is not None and latest.get("volume") is not None:
        amount = latest.get("close") * latest.get("volume")

    ret_tone, ret_indicator = _tone_from_number(ret_1d)
    short_tone = "green" if float(score.get("short_score", 0) or 0) >= 75 else "cyan" if float(score.get("short_score", 0) or 0) >= 60 else "orange"
    long_tone = "green" if float(score.get("long_score", 0) or 0) >= 65 else "cyan" if float(score.get("long_score", 0) or 0) >= 50 else "orange"

    render_bento_grid(
        [
            metric_card("最新收盘价", format_price(latest.get("close")), f"锚点 {_latest_date(hist)}", "cyan", "neutral"),
            metric_card("当日涨跌幅", format_percent(ret_1d), "相对上一交易日", ret_tone, ret_indicator),
            metric_card("成交量", format_number_cn(latest.get("volume"), 2), "最近交易日", "purple", "neutral"),
            metric_card("估算成交额", format_number_cn(amount, 2), "close x volume / 源成交额", "blue", "neutral"),
            metric_card("短线评分", format_price(score.get("short_score"), 1), "动量与量价优先", short_tone, "up" if score.get("short_score", 0) >= 60 else "neutral"),
            metric_card("中长线评分", format_price(score.get("long_score"), 1), "趋势与稳定性", long_tone, "up" if score.get("long_score", 0) >= 50 else "neutral"),
        ]
    )

    if warning:
        with st.container(border=True):
            st.markdown('<div class="chart-title"><span>数据源诊断</span><span class="pill pill-orange">Fallback</span></div>', unsafe_allow_html=True)
            st.warning("主数据源不可用时已自动兜底，页面展示的是实际成功获取的数据源。")
            with st.expander("Debug detail", expanded=False):
                st.write(warning)

    render_section_title("Market Story", "关键发现由价格结构、量能、动量指标和模型风险信号自动归纳。")
    render_insight_cards(_build_insights(score, hist, warning))

    render_section_title("Core Charts", "图表替代表格成为主叙事：价格、成交量、量价关系与技术指标分层展示。")
    top_left, top_right = st.columns([1.45, 1])
    with top_left:
        _render_chart_card("价格趋势", "K Line + MA", plot_price_trend(hist))
    with top_right:
        _render_chart_card("成交量", "Volume", plot_volume(hist))

    lower_left, lower_right = st.columns([1, 1])
    with lower_left:
        _render_chart_card("量价关系", "Close x Amount", plot_price_volume_scatter(hist))
    with lower_right:
        with st.container(border=True):
            st.markdown('<div class="chart-title"><span>技术指标</span><span class="pill pill-purple">Tabs</span></div>', unsafe_allow_html=True)
            tab_rsi, tab_macd, tab_kdj = st.tabs(["RSI", "MACD", "KDJ"])
            with tab_rsi:
                st.plotly_chart(plot_rsi(hist), use_container_width=True, config={"displayModeBar": False})
            with tab_macd:
                st.plotly_chart(plot_macd(hist), use_container_width=True, config={"displayModeBar": False})
            with tab_kdj:
                st.plotly_chart(plot_kdj(hist), use_container_width=True, config={"displayModeBar": False})

    fundamental_context = _render_fundamental_snapshot(score.get("code") or code, hist, score, dcf_assumptions)
    score = _enrich_score_with_fundamentals(score, fundamental_context)

    _render_explainable_scoring(score)

    render_section_title("Recent Market Data", "默认只展示最近 10 条，可读性优先；完整原始数据在 Debug 折叠区。")
    with st.container(border=True):
        render_recent_data_table(hist, rows=10)

    with st.container(border=True):
        st.markdown('<div class="chart-title"><span>报告输出</span><span class="pill pill-cyan">Saved</span></div>', unsafe_allow_html=True)
        st.success(f"分析报告已保存：{report_path}")
        st.write(score.get("summary"))


def _risk_tags(text: str) -> str:
    parts = [part.strip() for part in str(text or "").split("；") if part.strip()]
    if not parts:
        return '<span class="pill pill-cyan">暂无显著风险</span>'
    return " ".join(render_warning_badge(part) for part in parts[:2])


def _render_rank_cards(df: pd.DataFrame) -> None:
    cards = []
    for i, row in df.head(10).iterrows():
        cards.append(
            f'<div class="rank-card">'
            f'<div class="rank-top">'
            f'<div style="display:flex;gap:12px;align-items:flex-start">'
            f'<div class="rank-no">{i + 1}</div>'
            f'<div><div class="rank-name">{row.get("name", "-")}</div>'
            f'<div class="rank-code">{row.get("code", "-")} · {row.get("data_source", "-")}</div></div>'
            f'</div>{render_score_badge(row.get("composite_score"))}</div>'
            f'<div class="rank-metrics">'
            f'<div class="mini-metric"><span class="rank-label">最新价</span><strong>{format_price(row.get("close"))}</strong></div>'
            f'<div class="mini-metric"><span class="rank-label">短线</span><strong>{format_price(row.get("short_score"), 1)}</strong></div>'
            f'<div class="mini-metric"><span class="rank-label">中长线</span><strong>{format_price(row.get("long_score"), 1)}</strong></div>'
            f'</div>'
            f'<div class="insight-body">{row.get("summary", "-")}</div>'
            f'<div style="margin-top:14px">{_risk_tags(row.get("risk_flags"))}</div>'
            f'</div>'
        )
    st.markdown('<div class="rank-grid">' + "".join(cards) + "</div>", unsafe_allow_html=True)


def _render_screen_dashboard(df: pd.DataFrame, path: str, top: int, limit: int) -> None:
    scanned = int(df.attrs.get("scanned_count", limit) or limit)
    fetched = int(df.attrs.get("fetched_count", len(df)) or len(df))
    success_rate = float(df.attrs.get("success_rate", fetched / scanned if scanned else 0) or 0)
    avg_short = df["short_score"].mean() if "short_score" in df.columns and not df.empty else 0
    avg_long = df["long_score"].mean() if "long_score" in df.columns and not df.empty else 0

    render_bento_grid(
        [
            metric_card("扫描股票数量", f"{scanned}", "本轮股票池", "cyan", "neutral"),
            metric_card("成功获取数量", f"{fetched}", f"成功率 {success_rate:.0%}", "green" if success_rate >= 0.8 else "orange", "up"),
            metric_card("输出 Top N", f"{top}", "排行榜卡片", "purple", "neutral"),
            metric_card("平均短线评分", format_price(avg_short, 1), "Top 结果均值", "blue", "neutral"),
            metric_card("平均中长线评分", format_price(avg_long, 1), "Top 结果均值", "cyan", "neutral"),
            metric_card("结果文件", "CSV", path.split("/")[-1], "green", "neutral"),
        ]
    )

    errors = df.attrs.get("errors", [])
    if errors:
        with st.container(border=True):
            st.markdown('<div class="chart-title"><span>数据源诊断</span><span class="pill pill-orange">Partial</span></div>', unsafe_allow_html=True)
            st.warning("部分股票数据源请求失败，已跳过并继续生成榜单。")
            with st.expander("Debug detail", expanded=False):
                st.write("\n".join(errors[:20]))

    render_section_title("Top Ranked Opportunities", "排行榜卡片突出价格、分数、理由和风险标签，原始表格放在下方。")
    _render_rank_cards(df)

    render_section_title("Distribution & Positioning", "用分布和散点图观察候选池质量，不再只盯单行表格。")
    chart_left, chart_right = st.columns(2)
    with chart_left:
        _render_chart_card("分数分布", "Histogram", plot_score_distribution(df))
    with chart_right:
        _render_chart_card("短线分 vs 中长线分", "Scatter", plot_score_scatter(df))

    with st.container(border=True):
        st.markdown('<div class="chart-title"><span>行业 / 板块分布</span><span class="pill pill-orange">Reserved</span></div>', unsafe_allow_html=True)
        st.info("暂无行业数据。后续可接入同花顺行业/概念字段后在此展示板块分布。")

    render_section_title("Raw Results", "完整结果表格与 CSV 下载仍保留，用于复盘和导出。")
    with st.expander("Raw Result Table / Debug Data", expanded=False):
        st.dataframe(df, hide_index=True, use_container_width=True)
    csv = df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button("下载 CSV", data=csv, file_name="stock_screen_result.csv", mime="text/csv")
    st.success(f"选股结果已保存：{path}")


def _render_rotation_table(df: pd.DataFrame, title: str) -> None:
    with st.container(border=True):
        st.markdown(f'<div class="chart-title"><span>{title}</span><span class="pill pill-cyan">AkShare</span></div>', unsafe_allow_html=True)
        if df is None or df.empty:
            st.info("当前未获取到该分类的轮动数据。")
            return
        view = df.head(30).copy()
        keep = [
            "board_type",
            "board_name",
            "rotation_score",
            "board_pct",
            "net_flow",
            "flow_pct_d3",
            "flow_pct_d5",
            "leader",
            "leader_pct",
            "opportunity",
            "risk_note",
        ]
        view = view[[col for col in keep if col in view.columns]].rename(
            columns={
                "board_type": "类型",
                "board_name": "板块/行业/热点",
                "rotation_score": "轮动分",
                "board_pct": "当日涨跌幅",
                "net_flow": "主力净额(亿)",
                "flow_pct_d3": "3日涨跌幅",
                "flow_pct_d5": "5日涨跌幅",
                "leader": "领涨股",
                "leader_pct": "领涨股涨幅",
                "opportunity": "机会状态",
                "risk_note": "风险提示",
            }
        )
        for col in ["当日涨跌幅", "3日涨跌幅", "5日涨跌幅", "领涨股涨幅"]:
            if col in view.columns:
                view[col] = pd.to_numeric(view[col], errors="coerce").map(lambda x: "N/A" if pd.isna(x) else f"{x:+.2f}%")
        if "主力净额(亿)" in view.columns:
            view["主力净额(亿)"] = pd.to_numeric(view["主力净额(亿)"], errors="coerce").map(lambda x: "N/A" if pd.isna(x) else f"{x:+.2f}")
        st.dataframe(view, hide_index=True, use_container_width=True, height=min(620, 44 + len(view) * 38))


def _render_rotation_dashboard(payload: dict, top_n: int) -> None:
    summary = payload.get("summary", {}) if payload else {}
    combined = payload.get("combined", pd.DataFrame()) if payload else pd.DataFrame()
    industry = payload.get("industry", pd.DataFrame()) if payload else pd.DataFrame()
    concept = payload.get("concept", pd.DataFrame()) if payload else pd.DataFrame()

    render_section_title("板块 / 行业 / 热点轮动", "基于 AkShare 行业资金流、概念资金流和板块行情，追踪每日资金方向与机会状态。")
    if not payload or not payload.get("available"):
        st.warning("AkShare 轮动数据当前不可用。请稍后重试，或查看下方数据源诊断。")
        errors = (payload or {}).get("errors", [])
        if errors:
            with st.expander("查看数据源错误详情", expanded=False):
                st.dataframe(pd.DataFrame(errors), hide_index=True, use_container_width=True)
        return

    render_bento_grid(
        [
            metric_card("最强方向", str(summary.get("top_board") or "N/A"), str(summary.get("top_type") or "综合"), "green", "neutral"),
            metric_card("轮动分", format_price(summary.get("top_score"), 1), "资金 + 涨幅 + 延续性", "cyan", "neutral"),
            metric_card("主力净额", f"{float(summary.get('top_net_flow') or 0):+.2f} 亿", "最强方向净流入", "green" if (summary.get("top_net_flow") or 0) > 0 else "orange", "neutral"),
            metric_card("上涨方向数", str(summary.get("positive_pct_count") or 0), f"资金净流入 {summary.get('positive_flow_count') or 0}", "purple", "neutral"),
            metric_card("行业覆盖", str(summary.get("industry_count") or 0), "AkShare 行业资金流", "blue", "neutral"),
            metric_card("热点覆盖", str(summary.get("concept_count") or 0), "AkShare 概念资金流", "cyan", "neutral"),
        ]
    )

    if combined is not None and not combined.empty:
        chart_df = combined.head(int(top_n)).copy()
        fig = px.scatter(
            chart_df,
            x="net_flow",
            y="board_pct",
            size="rotation_score",
            color="board_type",
            hover_name="board_name",
            hover_data=["leader", "leader_pct", "opportunity"],
            labels={"net_flow": "主力净额(亿)", "board_pct": "当日涨跌幅(%)", "board_type": "类型"},
            color_discrete_sequence=["#22c55e", "#38bdf8", "#a78bfa"],
        )
        fig.update_layout(height=430, margin=dict(l=8, r=8, t=8, b=8), legend=dict(orientation="h"))
        _render_chart_card("资金流向 vs 当日强度", "Rotation Map", fig)

    tabs = st.tabs(["综合轮动榜", "行业轮动", "热点/概念轮动", "数据源诊断"])
    with tabs[0]:
        _render_rotation_table(combined.head(int(top_n)), "综合轮动榜")
    with tabs[1]:
        _render_rotation_table(industry, "行业轮动与资金")
    with tabs[2]:
        _render_rotation_table(concept, "热点/概念轮动与资金")
    with tabs[3]:
        st.caption(f"更新时间：{payload.get('updated_at')}；数据源：{payload.get('source')}")
        errors = payload.get("errors", [])
        if errors:
            st.dataframe(pd.DataFrame(errors), hide_index=True, use_container_width=True)
        else:
            st.success("本次 AkShare 轮动接口未记录错误。")


with st.sidebar:
    st.markdown("### Control Center")
    page = st.radio("分析模式", ["个股分析", "每日选股", "板块轮动"], index=0, help="个股分析用于深入复盘；每日选股用于扫描内置股票池；板块轮动追踪行业/热点资金方向。")
    provider_label = st.selectbox(
        "行情数据源",
        provider_options,
        index=_provider_index(config.get("data", {}).get("provider", "auto")),
        format_func=lambda x: provider_labels[x],
        help="默认建议使用 AkShare 优先。auto 会自动尝试多个数据源。",
    )
    config.setdefault("data", {})["provider"] = provider_label
    if "start_date" not in st.session_state:
        configured_start = config.get("market", {}).get("default_start_date")
        st.session_state["start_date"] = (
            pd.to_datetime(configured_start).date()
            if configured_start
            else _start_date_for_trading_days(180).date()
        )

    quick_60, quick_180, quick_year = st.columns(3)
    if quick_60.button("过去60", use_container_width=True):
        st.session_state["start_date"] = _start_date_for_trading_days(60).date()
    if quick_180.button("过去180", use_container_width=True):
        st.session_state["start_date"] = _start_date_for_trading_days(180).date()
    if quick_year.button("过去1年", use_container_width=True):
        st.session_state["start_date"] = _start_date_for_trading_days(252).date()
    start = st.date_input("行情起始日期", key="start_date", help="默认按当前日期回退 180 个交易日；快捷按钮会自动重算日期。")

    st.divider()
    stock_query = st.text_input(
        "股票代码 / 名称",
        value="",
        placeholder="输入 600519、贵州茅台、茅台等",
        help="支持 6 位股票代码、完整中文名和中文名称模糊匹配。",
    )
    code = ""
    name = ""
    matches = resolve_stock_query(stock_query, _stock_directory()) if stock_query.strip() else []
    if matches:
        labels = [
            f"{item.get('name', '-')} · {item.get('code', '-')} · {item.get('reason', '匹配')}"
            for item in matches
        ]
        selected_label = st.selectbox("匹配到的个股", labels, index=0)
        selected = matches[labels.index(selected_label)]
        code = str(selected.get("code") or "")
        name = str(selected.get("name") or "")
        st.caption(f"将使用 {name}（{code}）运行分析。")
    elif stock_query.strip():
        st.warning("没有匹配到股票。可以尝试输入 6 位代码、完整名称或更短的名称关键词。")

    st.divider()
    top = st.number_input("输出 Top N", min_value=5, max_value=50, value=int(config.get("ui", {}).get("default_top_n", 10)), step=1)
    limit = st.number_input("扫描股票数量", min_value=10, max_value=120, value=int(config.get("ui", {}).get("default_limit", 80)), step=10)
    mode = st.selectbox("选股模式", ["all", "short", "long"], format_func=lambda x: {"all": "综合", "short": "短线", "long": "中长线"}[x])

    with st.expander("估值假设设置", expanded=False):
        dcf_years = st.number_input("DCF 高增长期年数", min_value=1, max_value=10, value=5, step=1, help="简化 DCF 使用的显式预测年数。")
        dcf_growth = st.slider("现金流增长率", min_value=-20.0, max_value=30.0, value=5.0, step=0.5, help="未来显式预测期的年化现金流增长假设。")
        dcf_terminal_growth = st.slider("永续增长率", min_value=-5.0, max_value=6.0, value=2.0, step=0.25, help="长期稳定期增长假设，应低于折现率。")
        dcf_discount = st.slider("折现率", min_value=4.0, max_value=20.0, value=10.0, step=0.5, help="简化 DCF 折现率假设。")
        dcf_margin = st.slider("安全边际", min_value=0.0, max_value=50.0, value=20.0, step=1.0, help="用于计算安全边际价。")

    st.caption("金融仪表盘会自动隐藏冗长原始表格，把行情拆成可读图形与洞察卡片。")
    run = st.button("Run Radar", type="primary", use_container_width=True)

dcf_assumptions = {
    "years": int(dcf_years),
    "cashflow_growth": float(dcf_growth) / 100,
    "terminal_growth": float(dcf_terminal_growth) / 100,
    "discount_rate": float(dcf_discount) / 100,
    "margin_of_safety": float(dcf_margin) / 100,
}


start_str = start.strftime("%Y-%m-%d")
analysis_result = None
screen_result = None
rotation_result = None
run_error = None

if run and page == "个股分析":
    if not code:
        run_error = "请先输入股票代码或股票名称，并从匹配结果中选择一个个股。"
    else:
        with st.spinner("正在拉取多源行情并计算技术指标..."):
            try:
                analysis_result = StockAnalyzer(config).analyze(code, name=name, start=start_str)
            except Exception as exc:
                run_error = str(exc)
elif run and page == "每日选股":
    with st.spinner("正在扫描股票池并构建排行榜..."):
        try:
            screen_result = StockScreener(config).screen(mode=mode, top=int(top), limit=int(limit), start=start_str)
        except Exception as exc:
            run_error = str(exc)
elif run and page == "板块轮动":
    with st.spinner("正在拉取 AkShare 行业/概念资金流并计算每日轮动..."):
        try:
            rotation_result = RotationAnalyzer(config).analyze(top_n=int(top), force_refresh=True)
        except Exception as exc:
            run_error = str(exc)


hero_code = (f"{name} {code}".strip() if code else "未选择个股") if page == "个股分析" else f"Top {int(top)}"
hero_source = provider_label
hero_latest = "-"

if analysis_result:
    _, hist_for_hero, _ = analysis_result
    hero_source = _latest_source(hist_for_hero)
    hero_latest = _latest_date(hist_for_hero)
elif screen_result:
    df_for_hero, _ = screen_result
    if "date" in df_for_hero.columns and not df_for_hero.empty:
        screen_dt = pd.to_datetime(df_for_hero["date"].iloc[0], errors="coerce")
        hero_latest = screen_dt.strftime("%Y-%m-%d") if not pd.isna(screen_dt) else str(df_for_hero["date"].iloc[0])
    if "data_source" in df_for_hero.columns and not df_for_hero.empty:
        hero_source = ", ".join(sorted({str(v) for v in df_for_hero["data_source"].dropna().unique()}))
elif rotation_result:
    hero_source = "AkShare rotation"
    hero_latest = rotation_result.get("updated_at", "-")

render_hero(hero_code, hero_source, hero_latest, datetime.now().strftime("%Y-%m-%d %H:%M"))

if run_error:
    with st.container(border=True):
        st.markdown('<div class="chart-title"><span>运行失败</span><span class="pill pill-orange">Action needed</span></div>', unsafe_allow_html=True)
        st.error("本次请求没有成功生成结果。请尝试切换数据源、缩短日期范围或降低扫描数量。")
        with st.expander("Debug detail", expanded=False):
            st.write(run_error)
elif analysis_result:
    score, hist, report_path = analysis_result
    _render_analysis_dashboard(score, hist, report_path, dcf_assumptions)
elif screen_result:
    df, path = screen_result
    _render_screen_dashboard(df, path, int(top), int(limit))
elif rotation_result:
    _render_rotation_dashboard(rotation_result, int(top))
else:
    render_section_title("Ready When You Are", "从左侧控制台选择模式并运行，仪表盘会在这里生成 Bento 风格的行情分析。")
    render_bento_grid(
        [
            metric_card("默认数据源", provider_labels.get(provider_label, provider_label), "可在侧边栏切换", "cyan", "neutral"),
            metric_card("个股分析", "KPI + 图表", "输入代码后运行", "purple", "neutral"),
            metric_card("每日选股", f"Top {int(top)}", "扫描内置股票池", "blue", "neutral"),
            metric_card("板块轮动", "行业 + 热点", "追踪资金与扩散", "green", "neutral"),
        ]
    )
