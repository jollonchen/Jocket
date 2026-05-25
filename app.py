from __future__ import annotations

import copy
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from html import escape

import markdown
import pandas as pd
import streamlit as st

from src.ai_market_assistant import AIMarketAssistant, DEFAULT_MARKET_KEYWORDS
from src.config import load_config
from src.fundamental_analyzer import FundamentalAnalyzer
from src.fundamental_fetcher import FundamentalFetcher
from src.news_fetcher import NewsFetcher, news_items_to_frame
from src.cache_utils import FileCache
from src.providers.a_stock_data_provider import AStockDataProvider
from src.report_generator import ReportGenerator
from src.market_sentiment import MarketSentimentAnalyzer
from src.stock_analyzer import StockAnalyzer
from src.stock_signal_cards import build_market_signal_cards, build_stock_signal_cards, signal_cards_to_text
from src.stock_lookup import build_stock_directory, resolve_stock_query
from src.ui_components import (
    format_number_cn,
    format_percent,
    format_price,
    load_css,
    metric_card,
    plot_cashflow_vs_profit,
    plot_financial_revenue_profit,
    plot_kdj,
    plot_ice_point_month_stats,
    plot_limit_ecology,
    plot_macd,
    plot_market_sentiment_cycle,
    plot_market_sentiment_heatmap,
    plot_explainable_bar,
    plot_profitability,
    plot_price_trend,
    plot_price_volume_scatter,
    plot_ratings_snapshot,
    plot_risk_deductions,
    plot_rsi,
    plot_score_radar,
    plot_score_waterfall,
    plot_volume,
    plot_recent_5d_emotion,
    plot_recent_5d_limit_counts,
    plot_recent_5d_amount,
    render_company_profile,
    render_dimension_cards,
    render_evidence_table,
    render_financial_table,
    render_glass_dataframe,
    render_bento_grid,
    render_hero,
    render_insight_cards,
    render_ratings_list,
    render_recent_data_table,
    _render_emotion_cycle_position,
    render_section_title,
    render_valuation_metric_cards,
)
from src.utils import display_code
from src.valuation_engine import ValuationEngine
from src.tradingagents_ui import render_tradingagents_dashboard


st.set_page_config(page_title="Jocket", page_icon=None, layout="wide", initial_sidebar_state="collapsed")
load_css()

config = load_config()
config.setdefault("data", {})["provider"] = "auto"
INTERNAL_DATA_LABEL = "自动更新"


def _start_date_for_trading_days(days: int) -> pd.Timestamp:
    return (pd.Timestamp.now(tz="Asia/Shanghai").tz_localize(None).normalize() - pd.offsets.BDay(days))


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def _stock_directory() -> pd.DataFrame:
    return build_stock_directory()


@st.cache_resource(show_spinner=False)
def _analysis_executor() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=2, thread_name_prefix="jocket-analysis")


def _latest_date(hist: pd.DataFrame | None) -> str:
    if hist is None or hist.empty or "date" not in hist.columns:
        return "-"
    return pd.to_datetime(hist["date"].iloc[-1]).strftime("%Y-%m-%d")


def _has_cjk(value: str | None) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in str(value or ""))


def _chinese_name_for_code(stock_code: str | None, fallback: str | None = None) -> str:
    fallback_text = str(fallback or "").strip()
    code_text = str(stock_code or "").strip()
    if code_text:
        try:
            directory = _stock_directory()
            match = directory[directory["code"].astype(str) == code_text]
            if not match.empty:
                candidate = str(match.iloc[0].get("name") or "").strip()
                if _has_cjk(candidate):
                    return candidate
        except Exception:
            pass
    if _has_cjk(fallback_text):
        return fallback_text
    return fallback_text or code_text


def _compact_business_summary(business: str, max_chars: int = 86) -> str:
    text = re.sub(r"\s+", " ", str(business or "")).strip()
    text = re.sub(r"^\d{5,6}\s*", "", text)
    if not text or text in {"暂未获取", "当前数据源暂不支持"}:
        return ""

    sentences = [item.strip(" ；;，,") for item in re.split(r"[。！？!?]+", text) if item.strip(" ；;，,")]
    for sentence in sentences:
        if 10 <= len(sentence) <= max_chars and _has_cjk(sentence):
            return sentence + "。"

    clauses = []
    for part in re.split(r"[；;。！？!?]", text):
        for clause in re.split(r"(?<=、)|(?<=，)|,", part):
            clause = clause.strip(" ；;，,、")
            if clause and _has_cjk(clause) and clause not in clauses:
                clauses.append(clause)
    if not clauses:
        return ""
    summary = ""
    for clause in clauses:
        candidate = f"{summary}、{clause}" if summary else clause
        if len(candidate) + 1 > max_chars:
            break
        summary = candidate
    return (summary or clauses[0][:max_chars]).strip("、，,；;") + "。"


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
    volume = latest.get("volume")
    amount = latest.get("amount_est", latest.get("amount"))
    if amount is None and close and volume is not None:
        amount = close * float(volume or 0)

    ma20_gap = ((close / ma20) - 1) if close and ma20 else None
    ma60_gap = ((close / ma60) - 1) if close and ma60 else None

    if close > ma20 > ma60:
        trend_title, trend_tone = "多头结构占优", "green"
    elif close < ma20:
        trend_title, trend_tone = "短线趋势承压", "orange"
    else:
        trend_title, trend_tone = "趋势仍在确认", "cyan"
    trend_body = (
        f"收盘 {format_price(close)}，MA20 {format_price(ma20)}，MA60 {format_price(ma60)}；"
        f"较 MA20 {format_percent(ma20_gap) if ma20_gap is not None else 'N/A'}、较 MA60 {format_percent(ma60_gap) if ma60_gap is not None else 'N/A'}，"
        f"5日涨跌 {format_percent(ret_5d)}。判定：收盘>MA20>MA60 为多头，收盘<MA20 为承压。"
    )

    if vol_ratio >= 1.8 and ret_1d > 0:
        volume_title, volume_tone = "显著放量上涨", "green"
    elif vol_ratio >= 1.8 and ret_1d <= 0:
        volume_title, volume_tone = "高量分歧", "orange"
    elif vol_ratio >= 1.2:
        volume_title, volume_tone = "温和放量", "cyan"
    elif vol_ratio and vol_ratio < 0.8:
        volume_title, volume_tone = "缩量运行", "orange"
    else:
        volume_title, volume_tone = "量能中性", "cyan"
    volume_body = (
        f"量比20日均量 {format_price(vol_ratio, 2)}x，成交量 {format_number_cn(volume, 2)}，"
        f"估算成交额 {format_number_cn(amount, 2)}，当日涨跌 {format_percent(ret_1d)}。"
        "阈值：>1.80x 为显著放量，1.20-1.80x 为温和放量，<0.80x 为缩量。"
    )

    risk_flags = [flag for flag in score.get("risk_flags", []) if "未发现明显" not in flag]
    risk_control = next((item for item in score.get("short_breakdown", []) if item.get("dimension") == "风险控制"), {})
    risk_score = risk_control.get("score")
    risk_max = risk_control.get("max_score")
    if rsi >= 82:
        risk_title, risk_tone = "RSI 过热", "red"
    elif ret_5d >= 0.25:
        risk_title, risk_tone = "短线涨幅偏大", "orange"
    elif risk_flags:
        risk_title, risk_tone = "存在模型风险", "orange"
    else:
        risk_title, risk_tone = "风险可控", "green"
    risk_note = risk_flags[0] if risk_flags else "未触发主要模型内风险项"
    risk_body = (
        f"RSI14 {format_price(rsi, 1)}，5日涨跌 {format_percent(ret_5d)}，"
        f"风险控制 {format_price(risk_score, 1)} / {format_price(risk_max, 0)}。"
        f"规则：RSI>=82 高热，5日涨幅>=25% 偏快；当前提示：{risk_note}。"
    )

    source = INTERNAL_DATA_LABEL
    history_days = int(len(hist)) if hist is not None else 0
    latest_date = _latest_date(hist)
    model_status = "样本充足" if history_days >= 120 else "样本偏少"
    source_body = (
        f"最新交易日 {latest_date}，样本 {history_days} 个交易日，数据源 {source}。"
        f"模型状态：{model_status}；>=120 个交易日用于完整评分，低于该值会标记数据受限。"
    )

    return [
        {"label": "价格结构", "title": trend_title, "body": trend_body, "tone": trend_tone, "badge": f"5日 {format_percent(ret_5d)}"},
        {"label": "量能验证", "title": volume_title, "body": volume_body, "tone": volume_tone, "badge": f"{format_price(vol_ratio, 2)}x"},
        {"label": "风险量化", "title": risk_title, "body": risk_body, "tone": risk_tone, "badge": f"RSI {format_price(rsi, 1)}"},
        {"label": "数据锚点", "title": model_status, "body": source_body, "tone": "cyan", "badge": f"{history_days}日"},
    ]


def _render_chart_card(title: str, badge: str, fig, container_height: int | None = None, pill_class: str = "pill-cyan") -> None:
    container = st.container(border=True, height=container_height) if container_height else st.container(border=True)
    with container:
        st.markdown(
            f'<div class="chart-title"><span>{title}</span><span class="pill {pill_class}">{badge}</span></div>',
            unsafe_allow_html=True,
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False, "responsive": True}, key=f"chart_{title}")


def analyze_recent_5d_emotion(history: pd.DataFrame) -> tuple[str, str]:
    """
    分析近5日情绪评分趋势，返回（状态文本，药丸样式类名）
    """
    df = history.copy() if history is not None else pd.DataFrame()
    if df.empty:
        return "近5日", "pill-cyan"

    missing = pd.to_numeric(df.get("history_missing", 0), errors="coerce").fillna(0)
    counts = (
        pd.to_numeric(df.get("limit_up_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(df.get("broken_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(df.get("limit_down_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(df.get("strong_count", 0), errors="coerce").fillna(0)
    )
    df = df[(missing <= 0) & (counts > 0)].tail(5).copy()
    if df.empty or len(df) < 2:
        return "近5日", "pill-cyan"

    limit_count = pd.to_numeric(df.get("limit_up_count", 0), errors="coerce").fillna(0)
    max_streak = pd.to_numeric(df.get("max_streak", 0), errors="coerce").fillna(0)
    strong_count = pd.to_numeric(df.get("strong_count", 0), errors="coerce").fillna(0)
    broken_rate = pd.to_numeric(df.get("broken_rate", 0), errors="coerce").fillna(0) * 100
    down_count = pd.to_numeric(df.get("limit_down_count", 0), errors="coerce").fillna(0)

    if "emotion_score" in df.columns:
        emotion = pd.to_numeric(df["emotion_score"], errors="coerce").fillna(0).tolist()
    else:
        emotion = (
            (limit_count / max(limit_count.max(), 1) * 45)
            + (max_streak / max(max_streak.max(), 1) * 25)
            + (strong_count / max(strong_count.max(), 1) * 20)
            - broken_rate * 0.18
            - down_count * 1.2
            + 12
        ).clip(0, 100).tolist()

    latest_score = emotion[-1]
    prev_score = emotion[-2]
    change = latest_score - prev_score
    overall_change = emotion[-1] - emotion[0]

    if latest_score >= 70:
        status = "一致过热"
        tone = "pill-red"
    elif latest_score <= 35:
        status = "情绪冰点"
        tone = "pill-purple"
    else:
        if overall_change > 8:
            status = "震荡走强"
            tone = "pill-green"
        elif overall_change < -8:
            status = "情绪退潮"
            tone = "pill-orange"
        else:
            if change > 0:
                status = "分歧回暖"
                tone = "pill-cyan"
            else:
                status = "高位分歧" if latest_score > 55 else "低位震荡"
                tone = "pill-purple"

    return f"{status} {latest_score:.1f}", tone


def analyze_recent_5d_limit_counts(history: pd.DataFrame) -> tuple[str, str]:
    """
    分析近5日涨跌停家数，返回（状态文本，药丸样式类名）
    """
    df = history.copy() if history is not None else pd.DataFrame()
    if df.empty:
        return "近5日", "pill-cyan"

    missing = pd.to_numeric(df.get("history_missing", 0), errors="coerce").fillna(0)
    counts = (
        pd.to_numeric(df.get("limit_up_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(df.get("broken_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(df.get("limit_down_count", 0), errors="coerce").fillna(0)
    )
    df = df[(missing <= 0) & (counts > 0)].tail(5).copy()
    if df.empty:
        return "近5日", "pill-cyan"

    limit_ups = pd.to_numeric(df.get("limit_up_count", 0), errors="coerce").fillna(0).tolist()
    limit_downs = pd.to_numeric(df.get("limit_down_count", 0), errors="coerce").fillna(0).tolist()
    brokens = pd.to_numeric(df.get("broken_count", 0), errors="coerce").fillna(0).tolist()

    latest_up = limit_ups[-1]
    latest_down = limit_downs[-1]
    latest_broken = brokens[-1]

    avg_up = sum(limit_ups) / len(limit_ups)
    up_change_5d = limit_ups[-1] - limit_ups[0]

    if latest_down > 15:
        status = "跌停恐慌"
        tone = "pill-red"
    elif latest_up > 60:
        status = "多头高潮"
        tone = "pill-green"
    elif latest_up > avg_up * 1.2:
        if up_change_5d > 5:
            status = "接力升温"
            tone = "pill-green"
        else:
            status = "涨停放量"
            tone = "pill-cyan"
    elif latest_up < avg_up * 0.8:
        status = "接力衰退"
        tone = "pill-orange"
    else:
        total_limit_attempts = latest_up + latest_broken
        broken_rate = (latest_broken / total_limit_attempts) if total_limit_attempts > 0 else 0
        if broken_rate > 0.35:
            status = "分歧加剧"
            tone = "pill-purple"
        else:
            status = "多空平衡"
            tone = "pill-cyan"

    return f"{status} 涨{int(latest_up)}/跌{int(latest_down)}", tone


def analyze_recent_5d_amount(history: pd.DataFrame) -> tuple[str, str]:
    """
    分析近5日接力成交额趋势，返回（状态文本，药丸样式类名）
    """
    df = history.copy() if history is not None else pd.DataFrame()
    if df.empty:
        return "近5日", "pill-cyan"

    missing = pd.to_numeric(df.get("history_missing", 0), errors="coerce").fillna(0)
    counts = (
        pd.to_numeric(df.get("limit_up_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(df.get("broken_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(df.get("limit_down_count", 0), errors="coerce").fillna(0)
    )
    df = df[(missing <= 0) & (counts > 0)].tail(5).copy()
    if df.empty:
        return "近5日", "pill-cyan"

    amounts = (pd.to_numeric(df.get("limit_amount", 0), errors="coerce").fillna(0) / 1_0000_0000).tolist()

    latest_amt = amounts[-1]
    avg_amt = sum(amounts) / len(amounts)
    amt_change_5d = amounts[-1] - amounts[0]

    if latest_amt >= 150:
        status = "巨量突击"
        tone = "pill-red"
    elif latest_amt >= 80:
        status = "活跃流入"
        tone = "pill-green"
    elif latest_amt < 15:
        status = "地量冰点"
        tone = "pill-purple"
    elif amt_change_5d > 15:
        status = "放量进攻"
        tone = "pill-green"
    elif amt_change_5d < -15:
        status = "缩量退潮"
        tone = "pill-orange"
    elif latest_amt > avg_amt * 1.1:
        status = "放量进攻"
        tone = "pill-cyan"
    elif latest_amt < avg_amt * 0.9:
        status = "缩量整理"
        tone = "pill-orange"
    else:
        status = "平稳整理"
        tone = "pill-cyan"

    return f"{status} {latest_amt:.1f}亿", tone


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_fundamental_payload(code: str, latest_price: float | None) -> dict:
    return FundamentalFetcher(config).fetch(code, latest_price=latest_price)


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_stock_news_payload(code: str, name: str | None = None, boards: tuple[str, ...] = ()) -> dict:
    return NewsFetcher(config).fetch(code, name=name, boards=list(boards))


@st.cache_data(ttl=900, show_spinner=False)
def _fetch_a_stock_signal_bundle(code: str, trade_date: str | None = None) -> dict:
    return AStockDataProvider(config=config).stock_signal_bundle(code, trade_date=trade_date)


@st.cache_data(ttl=900, show_spinner=False)
def _fetch_a_stock_market_bundle(trade_date: str | None = None) -> dict:
    return AStockDataProvider(config=config).market_signal_bundle(trade_date=trade_date)


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_stock_analysis_core(code: str, name: str | None) -> tuple[dict, pd.DataFrame, str]:
    return StockAnalyzer(config).analyze(code, name=name, include_news=False)


def _stock_ai_summary_key(code: str, latest_date: str, score: dict) -> str:
    return (
        f"ai_summary_{code}_{latest_date}_"
        f"{score.get('short_score')}_{score.get('long_score')}_{score.get('rating')}"
    )


def _generate_stock_ai_summary(code: str, name: str, score: dict, hist: pd.DataFrame, fundamental_context: dict | None) -> str:
    latest_date = _latest_date(hist)
    summary_key = _stock_ai_summary_key(code, latest_date, score)
    cached = st.session_state.get(summary_key)
    if cached:
        return cached

    with st.spinner("正在生成当日个股趋势评级..."):
        summary = _generate_stock_ai_summary_core(code, name, score, hist, fundamental_context)
    st.session_state[summary_key] = summary
    return summary


def _generate_stock_ai_summary_core(code: str, name: str, score: dict, hist: pd.DataFrame, fundamental_context: dict | None) -> str:
    score_for_ai = copy.deepcopy(score)
    if not score_for_ai.get("news"):
        score_for_ai["news"] = NewsFetcher(config).fetch(code, name=name)
    return AIMarketAssistant(config, provider="gemini").generate_stock_one_liner(
        code,
        name or code,
        score_for_ai,
        hist,
        fundamental_context,
    )


def _render_dcf_card(metrics: dict, assumptions: dict) -> None:
    dcf = metrics.get("dcf", {}) or {}
    with st.container(border=True):
        st.markdown('<div class="chart-title"><span>简化 DCF 估值</span><span class="pill pill-orange">简化模型</span></div>', unsafe_allow_html=True)
        if not dcf.get("available"):
            st.warning("当前现金流口径不足，暂无法计算 DCF。")
        else:
            discount_pct = float(dcf.get("discount_pct") or 0)
            dcf_val_ind = "good" if discount_pct > 0 else "weak"
            price_ind = "low" if discount_pct > 0 else "high"
            discount_ind = "strong" if discount_pct > 0 else "weak"
            margin_ind = "strong" if discount_pct >= assumptions.get("margin_of_safety", 0.20) else "neutral"

            cards = [
                metric_card("DCF 每股估值", format_price(dcf.get("intrinsic_per_share")), "基于现金流折现", "cyan", dcf_val_ind),
                metric_card("当前价格", format_price(dcf.get("current_price")), "行情最新收盘价", "blue", price_ind),
                metric_card("折价 / 溢价", format_percent(dcf.get("discount_pct")), "正值代表低于估算值", "green" if discount_pct > 0 else "orange", discount_ind),
                metric_card("安全边际价", format_price(dcf.get("margin_price")), "扣除安全边际后", "purple", margin_ind),
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
        st.markdown('<div class="chart-title"><span>所属板块 / 概念热度</span><span class="pill pill-cyan">自动</span></div>', unsafe_allow_html=True)
        if boards is None or boards.empty:
            st.info("当前所属板块/概念数据不足，行业/题材评分暂以价格动量辅助判断。")
            return

        top_pct = float(summary.get("top_board_pct") or 0)
        top_ind = "strong" if top_pct >= 2.0 else "active" if top_pct >= 0.8 else "mild_strong" if top_pct > 0 else "mild_weak" if top_pct >= -1.5 else "weak"

        avg3_pct = float(summary.get('avg_top3_pct') or 0)
        avg3_ind = "strong" if avg3_pct >= 1.5 else "active" if avg3_pct >= 0.5 else "mild_strong" if avg3_pct > 0 else "mild_weak" if avg3_pct >= -1.0 else "weak"

        pos_count = int(summary.get("positive_count") or 0)
        pos_ind = "strong" if pos_count >= 8 else "active" if pos_count >= 4 else "mild_strong" if pos_count >= 2 else "weak" if pos_count == 0 else "mild_weak"

        cards = [
            metric_card("最强板块", str(summary.get("top_board") or "N/A"), "所属板块中涨幅最高", "green" if top_pct > 0 else "orange", top_ind),
            metric_card("最强涨幅", f"{top_pct:+.2f}%", "板块即时强度", "green" if top_pct > 0 else "red", top_ind),
            metric_card("前三均涨幅", f"{avg3_pct:+.2f}%", "板块扩散强度", "green" if avg3_pct > 0 else "orange", avg3_ind),
            metric_card("上涨板块数", str(pos_count), "所属方向扩散", "cyan", pos_ind),
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
        }
        keep = [col for col in ["board_name", "board_code", "board_pct", "flow_pct", "net_flow", "leader"] if col in view.columns]
        view = view[keep].rename(columns=rename)
        for col in ["板块涨幅", "资金流板块涨幅"]:
            if col in view.columns:
                view[col] = pd.to_numeric(view[col], errors="coerce").map(lambda x: "N/A" if pd.isna(x) else f"{x:+.2f}%")
        if "资金净额" in view.columns:
            view["资金净额"] = pd.to_numeric(view["资金净额"], errors="coerce").map(lambda x: "N/A" if pd.isna(x) else f"{x:+.2f}")
        render_glass_dataframe(view, height=min(420, 44 + len(view) * 38))


def _render_news_panel(news_payload: dict | None, title: str = "公开新闻与消息面") -> None:
    render_section_title(title, "整合公开新闻/快讯，并按个股或板块关键词评估关联度。")
    with st.container(border=True):
        st.markdown('<div class="chart-title"><span>消息面聚合</span><span class="pill pill-cyan">多源汇总</span></div>', unsafe_allow_html=True)
        if not news_payload or not news_payload.get("available"):
            st.info("当前未获取到可用公开新闻/快讯；不会因为消息面缺失而补写结论。")
            errors = (news_payload or {}).get("errors", [])
            if errors:
                with st.expander("消息源诊断", expanded=False):
                    render_glass_dataframe(pd.DataFrame([e if isinstance(e, dict) else {"message": str(e)} for e in errors[:20]]))
            return

        items = news_payload.get("items") or []
        top_item = items[0] if items else {}
        source_count = len({item.get("source") for item in items if item.get("source")})

        heat_score = float(news_payload.get("heat_score") or 0)
        heat_ind = "strong" if heat_score >= 80 else "active" if heat_score >= 60 else "mild_strong" if heat_score >= 40 else "mild_weak" if heat_score >= 20 else "weak"

        rel_score = int(top_item.get('relevance_score', 0) or 0)
        rel_ind = "strong" if rel_score >= 85 else "active" if rel_score >= 65 else "mild_strong" if rel_score >= 45 else "mild_weak" if rel_score >= 25 else "weak"

        news_count = len(items)
        count_ind = "high" if news_count >= 15 else "active" if news_count >= 6 else "mild_strong" if news_count >= 2 else "mild_weak" if news_count >= 1 else "weak"

        render_bento_grid(
            [
                metric_card("消息热度", format_price(news_payload.get("heat_score"), 1), "按关联度与覆盖度聚合", "green" if heat_score >= 60 else "cyan", heat_ind),
                metric_card("最高关联度", f"{rel_score} / 100", top_item.get("source", "公开源"), "green" if rel_score >= 60 else "orange", rel_ind),
                metric_card("命中消息数", str(news_count), f"{source_count} 个来源", "purple", count_ind),
                metric_card("更新", str(news_payload.get("updated_at", "-"))[-8:], news_payload.get("source", "公开信息源"), "blue", "fresh"),
            ]
        )
        summary_text = news_payload.get("summary", "暂无摘要")
        st.markdown(f'<div class="news-summary-box">{escape(summary_text)}</div>', unsafe_allow_html=True)
        table = news_items_to_frame(news_payload)
        if not table.empty:
            view = table.rename(
                columns={
                    "source": "来源",
                    "kind": "类型",
                    "date": "日期",
                    "title": "标题",
                    "relevance_score": "关联度",
                    "relevance_reason": "关联理由",
                    "url": "链接",
                }
            )
            render_glass_dataframe(view, height=min(460, 44 + len(view) * 38))
        if news_payload.get("errors"):
            with st.expander("消息源诊断", expanded=False):
                render_glass_dataframe(pd.DataFrame([e if isinstance(e, dict) else {"message": str(e)} for e in news_payload.get("errors", [])[:20]]))


def _render_research_signal_cards(cards: list[dict], title: str, subtitle: str, *, empty: str = "当前暂无可升级为独立卡片的高价值信号。") -> None:
    render_section_title(title, subtitle)
    if not cards:
        with st.container(border=True):
            st.info(empty)
        return
    ui_cards = []
    for card in cards:
        note = (
            f"{card.get('level', '待判断')}：{card.get('decision_note', '')} "
            f"阈值：{card.get('threshold_note', '')} 来源：{card.get('source', '-')}"
        )
        card_tone = str(card.get("tone") or "cyan")
        card_indicator = "neutral"
        if card_tone == "green":
            card_indicator = "strong"
        elif card_tone == "cyan":
            card_indicator = "active"
        elif card_tone == "orange":
            card_indicator = "mild_weak"
        elif card_tone == "red":
            card_indicator = "weak"
        ui_cards.append(
            metric_card(
                str(card.get("label") or "-"),
                str(card.get("value") or "N/A"),
                note[:260],
                card_tone,
                card_indicator,
            )
        )
    render_bento_grid(ui_cards)


def _render_signal_detail_tables(signal_payload: dict | None) -> None:
    if not signal_payload:
        return
    details = signal_payload.get("details", {}) or {}
    with st.expander("a-stock-data 原始明细与来源诊断", expanded=False):
        tabs = st.tabs(["研报", "公告", "资金流", "龙虎榜", "事件数据"])
        with tabs[0]:
            reports = pd.DataFrame(details.get("reports") or [])
            if reports.empty:
                st.info("暂无研报明细。")
            else:
                cols = [c for c in ["publishDate", "orgSName", "title", "emRatingName", "predictThisYearEps", "predictNextYearEps"] if c in reports.columns]
                render_glass_dataframe(reports[cols].head(30) if cols else reports.head(30), height=520)
        with tabs[1]:
            anns = pd.DataFrame(details.get("announcements") or [])
            if anns.empty:
                st.info("暂无公告明细。")
            else:
                render_glass_dataframe(anns[[c for c in ["date", "category", "title", "url"] if c in anns.columns]].head(30), height=520)
        with tabs[2]:
            flow = details.get("fund_flow_120d")
            if isinstance(flow, pd.DataFrame) and not flow.empty:
                render_glass_dataframe(flow.tail(60), height=520)
            else:
                st.info("暂无资金流明细。")
        with tabs[3]:
            lhb = details.get("dragon_tiger")
            if isinstance(lhb, pd.DataFrame) and not lhb.empty:
                render_glass_dataframe(lhb.head(50), height=520)
            else:
                st.info("暂无龙虎榜明细。")
        with tabs[4]:
            frames = []
            for key in ["lockup", "margin", "block_trade", "holders"]:
                df = details.get(key)
                if isinstance(df, pd.DataFrame) and not df.empty:
                    tmp = df.head(10).copy()
                    tmp.insert(0, "source_table", key)
                    frames.append(tmp)
            if frames:
                render_glass_dataframe(pd.concat(frames, ignore_index=True, sort=False), height=520)
            else:
                st.info("暂无解禁、两融、大宗交易或股东户数明细。")


def _build_fundamental_context(code: str, hist: pd.DataFrame, score: dict, dcf_assumptions: dict) -> dict | None:
    with st.spinner("正在获取公司基本信息、财务数据和估值指标..."):
        return _build_fundamental_context_common(
            code,
            hist,
            score,
            dcf_assumptions,
            fetch_payload=_fetch_fundamental_payload,
            fetch_signal=_fetch_a_stock_signal_bundle,
            fetch_news=_fetch_stock_news_payload,
        )


def _build_fundamental_context_core(code: str, hist: pd.DataFrame, score: dict, dcf_assumptions: dict) -> dict | None:
    return _build_fundamental_context_common(
        code,
        hist,
        score,
        dcf_assumptions,
        fetch_payload=lambda c, p: FundamentalFetcher(config).fetch(c, latest_price=p),
        fetch_signal=lambda c, d: AStockDataProvider(config=config).stock_signal_bundle(c, trade_date=d),
        fetch_news=lambda c, n, b: NewsFetcher(config).fetch(c, name=n, boards=list(b)),
    )


def _build_fundamental_context_common(
    code: str,
    hist: pd.DataFrame,
    score: dict,
    dcf_assumptions: dict,
    *,
    fetch_payload,
    fetch_signal,
    fetch_news,
) -> dict | None:
    latest_price = None
    if hist is not None and not hist.empty and "close" in hist.columns:
        latest_price = float(hist["close"].iloc[-1])
    try:
        payload = fetch_payload(code, latest_price)
        valuation = ValuationEngine(dcf_assumptions).analyze(payload)
        analysis = FundamentalAnalyzer().analyze(payload, valuation, score)
        trade_date = _latest_date(hist)
        signal_bundle = fetch_signal(code, trade_date if trade_date != "-" else None)
        signal_payload = build_stock_signal_cards(signal_bundle, display_code(code), payload.get("profile", {}), valuation.get("metrics", {}))
        boards = tuple((payload.get("sector", {}) or {}).get("summary", {}).get("primary_boards", []) or payload.get("profile", {}).get("belong_boards", []) or [])
        try:
            news_payload = fetch_news(code, payload.get("profile", {}).get("name"), boards)
        except Exception as news_exc:
            news_payload = {"available": False, "items": [], "heat_score": None, "errors": [{"source": "news", "message": str(news_exc)}]}
    except Exception as exc:
        signal_bundle = {"warnings": [{"source": "a-stock-data", "interface": "stock_signal_bundle", "message": str(exc)}]}
        signal_payload = {"cards": [], "valuation_cards": [], "event_cards": [], "details": {}}
        news_payload = score.get("news", {})
        if "payload" not in locals() or "valuation" not in locals() or "analysis" not in locals():
            return None
    return {"payload": payload, "valuation": valuation, "analysis": analysis, "a_stock_signal": signal_payload, "a_stock_bundle": signal_bundle, "news": news_payload}


def _render_fundamental_snapshot(code: str, hist: pd.DataFrame, score: dict, dcf_assumptions: dict, fundamental_context: dict | None) -> dict | None:
    render_section_title("公司基本面与估值快照", "Fundamental & Valuation Snapshot")
    if not fundamental_context:
        with st.container(border=True):
            st.markdown('<div class="chart-title"><span>基本面数据获取失败</span><span class="pill pill-orange">重试</span></div>', unsafe_allow_html=True)
            st.warning("基本面模块没有成功生成，但行情和技术评分仍可继续使用。")
        return None

    payload = fundamental_context.get("payload", {})
    valuation = fundamental_context.get("valuation", {})
    analysis = fundamental_context.get("analysis", {})
    profile = payload.get("profile", {})
    profile = copy.deepcopy(profile)
    display_name = _chinese_name_for_code(profile.get("code") or code, profile.get("name"))
    if display_name:
        profile["name"] = display_name
    metrics = valuation.get("metrics", {})
    ratings = valuation.get("ratings", {})
    annual = payload.get("annual", pd.DataFrame())
    quarterly = payload.get("quarterly", pd.DataFrame())

    business_raw = profile.get("business", "")

    final_summary = business_raw or analysis.get("profile_summary", "")

    render_company_profile(profile, final_summary)
    _render_sector_heat_card(payload.get("sector", {}))
    boards = tuple((payload.get("sector", {}) or {}).get("summary", {}).get("primary_boards", []) or profile.get("belong_boards", []) or [])
    news_payload = _fetch_stock_news_payload(profile.get("code") or code, profile.get("name"), boards) or score.get("news")
    _render_news_panel(news_payload, "公司公开新闻与消息面")
    signal_payload = fundamental_context.get("a_stock_signal", {}) or {}
    _render_research_signal_cards(
        signal_payload.get("valuation_cards", []),
        "预期与估值验证",
        "只展示能改变估值判断的信号：估值压力、业绩兑现难度和预期消化。",
    )
    _render_research_signal_cards(
        signal_payload.get("event_cards", []),
        "资金与事件信号",
        "把资金流、龙虎榜、解禁、筹码、融资、公告和热点归因压缩成可判断的研究卡片。",
    )
    render_valuation_metric_cards(metrics)

    rating_col, list_col = st.columns([1.2, 0.8])
    with rating_col:
        _render_chart_card("基本面评级快照", "1-5 分", plot_ratings_snapshot(ratings, height=560))
    with list_col:
        with st.container(border=True):
            st.markdown('<div class="chart-title"><span>核心财务与估值维度评分</span><span class="pill pill-cyan">综合</span></div>', unsafe_allow_html=True)
            render_ratings_list(ratings, metrics)
            st.caption("不可得指标显示 N/A，且不纳入综合评分。")

    _render_dcf_card(metrics, valuation.get("assumptions", dcf_assumptions))

    render_section_title("财务趋势", "年度和季度数据分开展示；不可得字段保持为空，不使用 0 冒充数据。")
    annual_tab, quarterly_tab = st.tabs(["年度财务", "季度财务"])
    for tab, data, label in [(annual_tab, annual, "年度"), (quarterly_tab, quarterly, "季度")]:
        with tab:
            if data is None or data.empty:
                st.info("当前暂未取得该周期财务数据。")
                continue
            c1, c2 = st.columns(2)
            with c1:
                _render_chart_card(f"{label} 收入与净利润", "收入 / 利润", plot_financial_revenue_profit(data))
            with c2:
                _render_chart_card(f"{label} 盈利能力", "ROE / ROA", plot_profitability(data))
            _render_chart_card(f"{label} 现金流 vs 净利润", "现金流", plot_cashflow_vs_profit(data))
            render_financial_table(data)

    render_section_title("财务质量摘要", "自动解释收入、利润质量、盈利能力、杠杆和分红能力。")
    render_insight_cards(analysis.get("quality_cards", []))

    with st.container(border=True):
        st.markdown('<div class="chart-title"><span>基本面评级解释</span><span class="pill pill-purple">研究视图</span></div>', unsafe_allow_html=True)
        st.write(analysis.get("fundamental_explanation"))
        st.info(analysis.get("research_view"))
        for note in analysis.get("limitations", []):
            st.caption(f"限制：{note}")
    _render_signal_detail_tables(signal_payload)
    return fundamental_context


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


def _score_band(score: float | None) -> str:
    score = _num(score)
    if score is None:
        return "暂无有效评分"
    if score >= 85:
        return "强势，但要防止高位追价"
    if score >= 70:
        return "偏强，适合进入观察池"
    if score >= 55:
        return "中性，需要等待更多共振"
    if score >= 40:
        return "偏弱，优先级应下调"
    return "弱势或风险偏高"


def _top_driver(items: list[dict], reverse: bool = True) -> str:
    usable = [item for item in items if _num(item.get("max_score")) and _num(item.get("score")) is not None]
    if not usable:
        return "暂无可解释维度"
    picked = sorted(usable, key=lambda item: float(item.get("score_rate", 0) or 0), reverse=reverse)[0]
    factors = picked.get("positive_factors" if reverse else "negative_factors", []) or []
    factor = str(factors[0]) if factors else picked.get("decision_impact", "")
    return f"{picked.get('dimension')} {format_price(picked.get('score'), 1)}/{format_price(picked.get('max_score'), 0)}，{factor}"


def _dashboard_card_indicator(label: str, score: dict, hist: pd.DataFrame, amount) -> str:
    latest = score.get("latest", {}) or {}
    if label == "最新价":
        close = _num(latest.get("close"))
        ma20 = _num(latest.get("ma20"))
        if close is not None and ma20:
            gap = close / ma20 - 1
            if gap >= 0.08:
                return "偏高"
            if gap >= 0.02:
                return "偏强"
            if gap > 0:
                return "活跃"
            if gap <= -0.08:
                return "偏低"
            if gap <= -0.02:
                return "偏弱"
            return "偏弱"
        return "中性"
    if label == "成交量":
        ratio = _num(latest.get("vol_ratio_20"))
        if ratio is not None:
            if ratio >= 1.8:
                return "强势"
            if ratio >= 1.2:
                return "活跃"
            if ratio >= 0.9:
                return "偏强"
            if ratio < 0.7:
                return "偏弱"
            return "偏弱"
        return "中性"
    if label == "估算成交额":
        amt = _num(amount)
        if amt is not None:
            if amt >= 1_000_000_000:
                return "强势"
            if amt >= 500_000_000:
                return "活跃"
            if amt >= 200_000_000:
                return "偏强"
            if amt < 100_000_000:
                return "偏弱"
            return "偏弱"
        return "中性"
    if label == "中长线评分":
        return _score_band(score.get("long_score")).split("，")[0]
    if label == "短线评分":
        return _score_band(score.get("short_score")).split("，")[0]
    return ""


def _metric_indicator_key(label: str, score: dict, hist: pd.DataFrame, amount, fallback: str = "neutral") -> str:
    text = _dashboard_card_indicator(label, score, hist, amount)
    if text in {"偏高", "承载弱", "偏弱", "弱势或风险偏高"}:
        return "high" if text == "偏高" else "mild_weak" if text == "偏弱" else "weak"
    if text in {"偏低"}:
        return "low"
    if text in {"活跃", "承载强", "偏强"}:
        return "active" if text == "活跃" else "mild_strong"
    if text in {"强势"}:
        return "strong"
    return fallback


def _dashboard_card_note(label: str, score: dict, hist: pd.DataFrame, amount) -> str:
    latest = score.get("latest", {}) or {}
    close = _num(latest.get("close"))
    if label == "最新价":
        ma20 = _num(latest.get("ma20"))
        if close is not None and ma20:
            gap = close / ma20 - 1
            return f"较 MA20 {format_percent(gap)}，决定短线结构"
        return f"锚点 {_latest_date(hist)}"
    if label == "当日涨跌幅":
        ret = _num(latest.get("ret_1d"))
        vol_ratio = _num(latest.get("vol_ratio_20"))
        if ret is not None and vol_ratio is not None:
            if ret > 0 and vol_ratio > 1.2:
                return f"上涨配合 {vol_ratio:.2f}x 量能，承接增强"
            if ret < 0 and vol_ratio > 1.2:
                return f"下跌伴随 {vol_ratio:.2f}x 量能，分歧放大"
            return f"量能 {vol_ratio:.2f}x，价格确认度一般"
        return "相对上一交易日"
    if label == "成交量":
        ratio = _num(latest.get("vol_ratio_20"))
        if ratio is None:
            return "观察活跃度变化"
        if ratio >= 1.8:
            return f"为 20 日均量 {ratio:.2f}x，资金关注度高"
        if ratio >= 1:
            return f"略高于 20 日均量 {ratio:.2f}x"
        return f"低于 20 日均量，仅 {ratio:.2f}x"
    if label == "估算成交额":
        amt = _num(amount)
        if amt is None:
            return "用于判断交易承载力"
        if amt >= 500_000_000:
            return "交易承载力较强，短线进出更顺"
        if amt >= 150_000_000:
            return "交易活跃度可用，但不适合过重仓位"
        return "成交承载偏弱，需控制滑点和仓位"
    if label == "短线评分":
        return f"{_score_band(score.get('short_score'))}；主驱动：{_top_driver(score.get('short_breakdown', []), True)}"
    if label == "中长线评分":
        return f"{_score_band(score.get('long_score'))}；短板：{_top_driver(score.get('long_breakdown', []), False)}"
    return ""


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


def _find_signal_card(signal_payload: dict, label: str) -> dict:
    for group in ("cards", "valuation_cards", "event_cards"):
        for card in signal_payload.get(group, []) or []:
            if card.get("label") == label:
                return card
    return {}


def _money_flow_evidence(bundle: dict, signal_payload: dict) -> dict:
    card = _find_signal_card(signal_payload, "资金流验证")
    rows = bundle.get("fund_flow_120d") or bundle.get("fund_flow_minute") or []
    frame = pd.DataFrame(rows if isinstance(rows, list) else [])
    evidence = {
        "available": bool(card) or not frame.empty,
        "card_score": _num(card.get("score")) if card else None,
        "card_level": card.get("level") if card else None,
        "card_value": card.get("value") if card else None,
        "latest_main_net_inflow": None,
        "main_net_inflow_20d": None,
        "positive_flow_days_20d": None,
    }
    if not frame.empty and "main_net_inflow" in frame.columns:
        series = pd.to_numeric(frame["main_net_inflow"], errors="coerce").dropna()
        recent = series.tail(20)
        if not recent.empty:
            evidence["latest_main_net_inflow"] = float(recent.iloc[-1])
            evidence["main_net_inflow_20d"] = float(recent.sum())
            evidence["positive_flow_days_20d"] = int((recent > 0).sum())
    return evidence


def _recompute_score_totals(score: dict, *, fundamental_context: dict | None = None, preserve_fundamental_bonus: bool = False) -> None:
    short_breakdown = score.get("short_breakdown", []) or []
    long_breakdown = score.get("long_breakdown", []) or []
    score["short_parts"] = {item["dimension"]: item["score"] for item in short_breakdown}
    score["long_parts"] = {item["dimension"]: item["score"] for item in long_breakdown}
    score["short_score"] = min(100, max(0, round(sum(score["short_parts"].values()), 1)))
    score["long_score"] = min(100, max(0, round(sum(score["long_parts"].values()), 1)))
    if preserve_fundamental_bonus and fundamental_context:
        overall = ((fundamental_context.get("valuation", {}) or {}).get("ratings", {}) or {}).get("overall") or 0
        score["composite_score"] = round(float(score.get("short_score", 0) or 0) * 0.55 + score["long_score"] * 0.30 + float(overall) / 5 * 15, 1)
    else:
        score["composite_score"] = round(score["short_score"] * 0.6 + score["long_score"] * 0.4, 1)


def _external_signal_status(fundamental_context: dict) -> dict:
    payload = fundamental_context.get("payload", {}) or {}
    sector_summary = ((payload.get("sector", {}) or {}).get("summary", {}) or {})
    signal_payload = fundamental_context.get("a_stock_signal", {}) or {}
    bundle = fundamental_context.get("a_stock_bundle", {}) or {}
    news_payload = fundamental_context.get("news", {}) or {}
    flow_ev = _money_flow_evidence(bundle, signal_payload)
    return {
        "sector_available": bool(sector_summary.get("available")),
        "sector_flow_available": _num(sector_summary.get("net_flow_sum")) is not None,
        "stock_flow_available": bool(flow_ev.get("available")),
        "news_available": bool(news_payload.get("available")) or _num(news_payload.get("heat_score")) is not None,
        "news_heat_score": _num(news_payload.get("heat_score")),
        "money_flow": flow_ev,
    }


def _enrich_sector_proxy_item(score: dict, fundamental_context: dict) -> None:
    payload = fundamental_context.get("payload", {})
    profile = payload.get("profile", {})
    sector_payload = payload.get("sector", {}) or {}
    sector_summary = sector_payload.get("summary", {}) or {}
    signal_payload = fundamental_context.get("a_stock_signal", {}) or {}
    bundle = fundamental_context.get("a_stock_bundle", {}) or {}
    news_payload = fundamental_context.get("news", {}) or {}
    money_flow = _money_flow_evidence(bundle, signal_payload)
    industry = profile.get("industry") or "暂未获取"
    industry_cn = profile.get("industry_cn") or "暂未获取"
    sector = profile.get("sector") or "暂未获取"
    boards = sector_summary.get("primary_boards", []) or profile.get("belong_boards", []) or []
    top_board = sector_summary.get("top_board")
    top_pct = _num(sector_summary.get("top_board_pct"))
    avg_top3 = _num(sector_summary.get("avg_top3_pct"))
    positive_count = int(sector_summary.get("positive_count") or 0)
    net_flow_sum = _num(sector_summary.get("net_flow_sum"))
    news_heat = _num(news_payload.get("heat_score"))
    hot_card = _find_signal_card(signal_payload, "热点归因匹配")
    source = sector_summary.get("source", "efinance")
    short_breakdown = score.get("short_breakdown", [])
    for item in short_breakdown:
        if item.get("dimension") != "行业/题材代理":
            continue
        item["dimension"] = "行业/题材/资金催化"
        sector_score = 0
        positives, negatives = [], []
        if sector_summary.get("available"):
            if top_pct is not None:
                if top_pct >= 3:
                    sector_score += 3; positives.append(f"最强所属板块 {top_board} 涨幅 {top_pct:.2f}%")
                elif top_pct >= 1:
                    sector_score += 2; positives.append(f"最强所属板块 {top_board} 涨幅为正")
                elif top_pct < 0:
                    negatives.append(f"最强所属板块 {top_board} 仍为下跌，板块强度不足")
            if avg_top3 is not None:
                if avg_top3 >= 1:
                    sector_score += 2; positives.append(f"前三所属板块平均涨幅 {avg_top3:.2f}%")
                elif avg_top3 < 0:
                    negatives.append(f"前三所属板块平均涨幅 {avg_top3:.2f}%，板块联动偏弱")
            if positive_count >= 4:
                sector_score += 2; positives.append(f"所属板块中 {positive_count} 个为上涨，扩散度较好")
            elif positive_count > 0:
                sector_score += 1; positives.append(f"所属板块中 {positive_count} 个为上涨")
            if net_flow_sum is not None:
                if net_flow_sum > 0:
                    sector_score += 2; positives.append(f"已匹配板块资金净流入合计 {net_flow_sum:.2f}")
                else:
                    negatives.append(f"已匹配板块资金净流出合计 {net_flow_sum:.2f}")
            else:
                negatives.append("板块资金流暂未完全匹配，资金项不参与本次加分")
        else:
            negatives.append("所属板块数据不足，暂以个股价格动量和成交活跃度辅助判断")
        flow_card_score = _num(money_flow.get("card_score"))
        flow_20d = _num(money_flow.get("main_net_inflow_20d"))
        latest_flow = _num(money_flow.get("latest_main_net_inflow"))
        if money_flow.get("available"):
            if flow_card_score is not None and flow_card_score >= 70:
                sector_score += 3; positives.append(f"主力资金卡片为{money_flow.get('card_level') or '资金确认'}")
            elif flow_20d is not None and flow_20d > 0:
                sector_score += 2; positives.append(f"近20条主力资金净流入合计 {format_number_cn(flow_20d)}")
            elif latest_flow is not None and latest_flow > 0:
                sector_score += 1; positives.append(f"最新主力资金净流入 {format_number_cn(latest_flow)}")
            else:
                negatives.append("主力资金净流入未形成确认")
        else:
            negatives.append("个股主力资金流暂未取得，本项不加分")
        if news_heat is not None:
            if news_heat >= 70:
                sector_score += 2; positives.append(f"新闻/公告热度 {news_heat:.1f}，催化强")
            elif news_heat >= 45:
                sector_score += 1; positives.append(f"新闻/公告热度 {news_heat:.1f}，有跟踪价值")
            elif news_payload.get("available"):
                negatives.append(f"新闻/公告热度 {news_heat:.1f}，催化不强")
        elif news_payload.get("available"):
            sector_score += 1; positives.append("已取得相关公开新闻/公告，作为催化验证")
        else:
            negatives.append("新闻/公告催化未取得，本项不加分")
        if hot_card:
            hot_score = _num(hot_card.get("score"))
            if hot_score is not None and hot_score >= 60:
                sector_score += 1; positives.append(f"同花顺热点归因为{hot_card.get('level') or '可用'}")
            else:
                negatives.append("热点归因匹配度一般")
        item["score"] = round(max(0, min(15, sector_score)), 1)
        item["score_rate"] = round(item["score"] / 15, 3)
        item["positive_factors"] = positives or ["所属板块、资金和新闻数据已接入，但强度信号不突出"]
        item["negative_factors"] = negatives or ["暂无明显外部信号扣分项"]
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
            "main_net_inflow_latest": latest_flow,
            "main_net_inflow_20d": flow_20d,
            "positive_flow_days_20d": money_flow.get("positive_flow_days_20d"),
            "money_flow_card_score": flow_card_score,
            "news_heat_score": news_heat,
            "news_source": news_payload.get("source"),
            "hot_reason_score": _num(hot_card.get("score")) if hot_card else None,
            "board_source": source,
        })
        item["data_points"] = data_points
        item["logic"] = (
            "自动识别行业/概念板块强度、板块资金流、个股主力资金流、新闻/公告热度与热点归因；"
            "缺失项只做扣分/不加分，不再用旧的纯价格代理冒充外部信号。"
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
            "该分数反映所属板块/概念强度、主力资金确认和新闻催化质量；分数低时代表外部验证不足，而不是数据被忽略。"
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
    valuation_avg = _avg_available([scores.get("P/E"), scores.get("P/B"), scores.get("P/S"), scores.get("Dividend Yield")])

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
        negative_growth.append("缺少可比营收或净利润序列，成长分按保守口径处理")

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
    if valuation_avg is None:
        negative_val.append("PE/PB/PS/股息率可用性不足，估值分按保守口径处理")

    valuation_item = _score_item(
        "估值与股息",
        valuation_score,
        10,
        "综合 PE、PB、PS 和股息率的 1-5 分评分，转换为 10 分制；DCF 仅单独展示，不纳入评分。",
        {
            "pe_ttm": metrics.get("pe_ttm"),
            "pb": metrics.get("pb"),
            "ps": metrics.get("ps"),
            "dividend_yield": metrics.get("dividend_yield"),
        },
        positive_val,
        negative_val,
        "估值分高代表当前估值压力相对可解释；低分不等于不能研究，但需要更强成长或催化支撑。",
    )

    for note in valuation.get("limitations", []):
        if "AkShare" in note or "暂不支持" in note:
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
        return "继续观察（基本面待补充）", "技术面信号尚可继续跟踪，但基本面证据不足，暂不提高研究优先级。"

    if short_score >= 75 and risk_score >= 10 and fundamental_overall >= 3.5:
        return "重点研究", "短线趋势、风险控制和基本面评级形成较好共振，适合纳入重点研究池，但不等于直接买入。"
    if short_score >= 70 and fundamental_overall >= 2.8:
        return "优先观察", "短线信号偏强，基本面评级不弱，适合进入观察池并等待买点和外部验证。"
    if short_score >= 70 and fundamental_overall < 2.8:
        return "短线观察，基本面待验证", "短线信号较强，但基本面评级偏弱或估值压力较大，更适合短线观察。"
    if short_score < 60 and fundamental_overall >= 3.5:
        return "基本面较强，短线暂不追入", "基本面评级较好，但短线结构偏弱，当前不追价，等价格结构改善后再提高优先级。"
    if short_score < 55 and long_score < 55 and fundamental_overall < 2.8:
        return "暂不优先", "技术面和基本面暂未形成优势，当前不作为优先研究标的。"
    return "谨慎观察", "技术面和基本面信号不够一致，适合继续跟踪并等待更明确证据。"


def _enrich_score_with_fundamentals(score: dict, fundamental_context: dict | None) -> dict:
    if not fundamental_context:
        return score
    enriched = copy.deepcopy(score)
    if fundamental_context.get("news"):
        enriched["news"] = fundamental_context.get("news")
    _enrich_sector_proxy_item(enriched, fundamental_context)
    formula = copy.deepcopy(enriched.get("formula", {}))
    formula.setdefault("short", {})["行业/题材/资金催化"] = [
        "所属板块涨幅/前三板块均值/上涨扩散度最高 +8",
        "匹配板块资金净流入最高 +2",
        "个股主力资金流确认最高 +3",
        "新闻公告热度或热点归因最高 +2",
        "缺失项不加分，负向资金或板块走弱进入扣分说明",
    ]
    formula.get("short", {}).pop("行业/题材代理", None)
    enriched["formula"] = formula
    _recompute_score_totals(enriched)
    new_items, fundamental_limitations, integrated = _build_integrated_long_items(fundamental_context)
    if integrated and new_items:
        long_breakdown = enriched.get("long_breakdown", [])
        replacements = [
            ({"质量占位", "质量初筛"}, new_items[0]),
            ({"成长占位", "成长初筛"}, new_items[1]),
            ({"估值占位", "估值初筛"}, new_items[2]),
        ]
        for old_names, new_item in replacements:
            long_breakdown = _replace_breakdown_item(long_breakdown, old_names, new_item)
        enriched["long_breakdown"] = long_breakdown
        _recompute_score_totals(enriched, fundamental_context=fundamental_context, preserve_fundamental_bonus=True)
        enriched["fundamental_integrated"] = True
    else:
        _recompute_score_totals(enriched)
        enriched["fundamental_integrated"] = False

    rating, explanation = _rating_with_fundamentals(enriched, fundamental_context, enriched["fundamental_integrated"])
    enriched["rating"] = rating
    enriched["rating_explanation"] = explanation

    base_limitations = [
        note for note in enriched.get("limitations", [])
        if "未接入完整财务数据" not in note and "质量/成长/估值为占位分" not in note
        and "若基本面模块未能返回财务/估值数据" not in note
        and "行业热度、概念强度和主力资金流尚未接入评分" not in note
        and "行业热度、概念强度和主力资金流向未接入评分" not in note
        and "未取得基本面增强上下文时，行业/题材维度使用价格动量代理" not in note
    ]
    external = _external_signal_status(fundamental_context)
    if enriched["fundamental_integrated"]:
        base_limitations.append("财务和非 DCF 估值指标已参与中长线评分；DCF 仅作单独估值参考。")
    else:
        base_limitations.append("基本面数据不足，财务/成长/估值仍未完整参与评分。")
    if external["sector_available"]:
        base_limitations.append("行业/概念强度已参与短线评分；若只能取得板块归属而缺少实时涨幅或资金流，则对应子项不加分。")
    else:
        base_limitations.append("行业/概念归属暂未取得，外部信号维度退回保守口径。")
    if external["stock_flow_available"]:
        base_limitations.append("个股主力资金流已参与短线外部信号评分。")
    else:
        base_limitations.append("个股主力资金流暂未取得，资金确认子项不加分。")
    if external["news_available"]:
        base_limitations.append("新闻/公告热度已参与短线外部信号评分。")
    else:
        base_limitations.append("新闻/公告催化暂未取得，催化子项不加分。")
    base_limitations.extend(fundamental_limitations)
    enriched["limitations"] = list(dict.fromkeys(base_limitations + ["评分仅用于研究辅助，不构成投资建议"]))
    enriched["score_explanations"] = _score_explanations_with_context(enriched, fundamental_context)
    enriched["summary"] = f"{rating}。{explanation} 风险提示：" + "；".join(enriched.get("risk_flags", [])[:2])
    return enriched


def _stock_job_signature(code: str, dcf_assumptions: dict) -> tuple:
    return (str(code or ""), tuple(sorted((dcf_assumptions or {}).items())))


def _market_job_signature(trade_date, window_days: int) -> tuple:
    return (pd.to_datetime(trade_date).strftime("%Y-%m-%d"), int(window_days or 60))


def _set_job_stage(progress: dict | None, stage: str) -> None:
    if progress is not None:
        progress["stage"] = stage


def _run_stock_analysis_job(code: str, name: str, dcf_assumptions: dict, progress: dict | None = None) -> dict:
    _set_job_stage(progress, "fetch")
    base_result = StockAnalyzer(config).analyze(code, name=name, include_news=False)
    score_tmp, hist_tmp, report_path = base_result
    _set_job_stage(progress, "compute")
    fundamental_context = _build_fundamental_context_core(code, hist_tmp, score_tmp, copy.deepcopy(dcf_assumptions))
    score_for_summary = _enrich_score_with_fundamentals(score_tmp, fundamental_context) if fundamental_context else score_tmp
    stock_name_for_summary = name or code
    _set_job_stage(progress, "view")
    try:
        ai_summary = _generate_stock_ai_summary_core(code, stock_name_for_summary, score_for_summary, hist_tmp, fundamental_context)
    except Exception as exc:
        ai_summary = f"AI 摘要暂未生成：{type(exc).__name__}: {exc}"
    _set_job_stage(progress, "done")
    return {
        "code": code,
        "name": stock_name_for_summary,
        "dcf_assumptions": copy.deepcopy(dcf_assumptions),
        "analysis_result": (score_for_summary, hist_tmp, report_path),
        "fundamental_context_result": fundamental_context,
        "ai_stock_summary": ai_summary,
    }


def _run_market_sentiment_job(trade_date, window_days: int, progress: dict | None = None) -> dict:
    _set_job_stage(progress, "fetch")
    sentiment_result = MarketSentimentAnalyzer(config).analyze(
        trade_date,
        window_days=int(window_days or 60),
        force_refresh=False,
        backfill_history=True,
    )
    _set_job_stage(progress, "compute")
    trade_date_text = pd.to_datetime(trade_date).strftime("%Y-%m-%d")
    market_bundle = AStockDataProvider(config=config).market_signal_bundle(trade_date=trade_date_text)
    _set_job_stage(progress, "view")
    sentiment_result["a_stock_market_bundle"] = market_bundle
    sentiment_result["a_stock_market_signal"] = build_market_signal_cards(market_bundle)
    _set_job_stage(progress, "done")
    return {
        "trade_date": pd.to_datetime(trade_date).date(),
        "window_days": int(window_days or 60),
        "sentiment_result": sentiment_result,
    }


def _job_step_class(stage: str, step: str) -> str:
    order = {"fetch": 1, "compute": 2, "view": 3, "done": 4}
    step_order = {"fetch": 1, "compute": 2, "view": 3}
    current = order.get(stage, 1)
    target = step_order[step]
    if current > target:
        return "is-complete"
    if current == target:
        return "is-active"
    return "is-pending"


def _render_background_job_panel(title: str, description: str, stage: str = "fetch") -> None:
    fetch_class = _job_step_class(stage, "fetch")
    compute_class = _job_step_class(stage, "compute")
    view_class = _job_step_class(stage, "view")
    st.markdown(
        f"""
        <section class="jocket-job-panel" aria-live="polite">
          <div class="jocket-job-head">
            <div>
              <div class="jocket-job-kicker">I'm Jocketing</div>
              <div class="jocket-job-title">{escape(title)}</div>
            </div>
            <span>后台运行</span>
          </div>
          <p>{escape(description)}</p>
          <div class="jocket-job-track" aria-hidden="true">
            <i></i>
          </div>
          <div class="jocket-job-steps" aria-hidden="true">
            <b class="{fetch_class}">取数</b>
            <b class="{compute_class}">计算</b>
            <b class="{view_class}">生成视图</b>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


@st.fragment(run_every="2s")
def _render_background_job_fragment(job_state_key: str, title: str, description: str) -> None:
    job = st.session_state.get(job_state_key) or {}
    future = job.get("future")
    if future is not None and future.done():
        st.rerun()
    progress = job.get("progress") or {}
    _render_background_job_panel(title, description, str(progress.get("stage") or "fetch"))


def _score_explanations_with_context(score: dict, fundamental_context: dict) -> list[str]:
    ratings = fundamental_context.get("valuation", {}).get("ratings", {})
    metrics = fundamental_context.get("valuation", {}).get("metrics", {})
    external = _external_signal_status(fundamental_context)
    overall = ratings.get("overall")
    short_score = _num(score.get("short_score")) or 0
    long_score = _num(score.get("long_score")) or 0
    short_items = score.get("short_breakdown", [])
    long_items = score.get("long_breakdown", [])
    text = []
    text.append(
        f"短线评分 {format_price(short_score, 1)} / 100，属于“{_score_band(short_score)}”。"
        f"本轮最主要正向驱动是 {_top_driver(short_items, True)}；最需要警惕的是 {_top_driver(short_items, False)}。"
    )
    text.append(
        "外部信号已接入短线评分："
        f"行业/概念{'可用' if external['sector_available'] else '不可用'}，"
        f"板块资金{'可用' if external['sector_flow_available'] else '不可用'}，"
        f"个股主力资金{'可用' if external['stock_flow_available'] else '不可用'}，"
        f"新闻/公告热度{'可用' if external['news_available'] else '不可用'}。"
        "不可用项只是不加分，不再被当作“已接入但忽略”。"
    )
    if score.get("fundamental_integrated"):
        roe = metrics.get("roe")
        pb = metrics.get("pb")
        pe = metrics.get("pe_ttm")
        text.append(
            f"中长线评分 {format_price(long_score, 1)} / 100，已纳入财务质量、成长表现、非 DCF 估值与股息。"
            f"基本面综合评分为 {overall if overall is not None else 'N/A'} / 5；"
            f"ROE {format_percent(roe) if roe is not None else 'N/A'}、PB {format_price(pb, 2) if pb is not None else 'N/A'}、PE {format_price(pe, 2) if pe is not None else 'N/A'} 是本次估值判断的关键输入。"
        )
    else:
        text.append(
            f"中长线评分 {format_price(long_score, 1)} / 100，当前更多依赖长期均线、回撤和波动结构；"
            "财务和估值证据不足时，不把它上升为中长期投资结论。"
        )
    long_items = sorted(long_items, key=lambda x: x.get("score_rate", 0), reverse=True)
    if long_items:
        best = "、".join(f"{item['dimension']}({item['score']}/{item['max_score']})" for item in long_items[:3])
        weak = "、".join(f"{item['dimension']}({item['score']}/{item['max_score']})" for item in sorted(long_items, key=lambda x: x.get("score_rate", 0))[:3])
        text.append(f"中长线贡献最大的维度是 {best}；拖累项是 {weak}。因此结论应围绕强项确认、弱项排雷，而不是只看总分。")
    text.append("执行建议：强趋势但风险分低时优先等回踩或缩量确认；基本面评分低时只做短线观察；只有趋势、行业/概念强度、资金确认和财务质量同时改善，才提高研究优先级。")
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
            st.markdown("- 当前版本：中长线评分已纳入可获取的财务质量、成长表现、非 DCF 估值与股息指标，同时保留长期趋势和稳定性。")
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

    render_section_title("可解释评分", "评分不是黑盒：每个维度都能展开查看公式、触发条件、底层数据、加分项和扣分项。")
    sh_score = float(score.get('short_score', 0) or 0)
    sh_indicator = "strong" if sh_score >= 85 else "mild_strong" if sh_score >= 70 else "mild_weak" if sh_score >= 55 else "weak"

    ln_score = float(score.get('long_score', 0) or 0)
    ln_indicator = "strong" if ln_score >= 85 else "mild_strong" if ln_score >= 70 else "mild_weak" if ln_score >= 55 else "weak"

    rating_indicator = "strong" if any(w in rating for w in ["优先", "重点", "强势"]) else "weak" if any(w in rating for w in ["回避", "风险", "警告"]) else "mild_weak" if "谨慎" in rating else "active"

    risk_val = float(risk_control.get('score', 0) or 0)
    risk_indicator = "good" if risk_val >= 12 else "active" if risk_val >= 8 else "mild_weak" if risk_val >= 5 else "weak"

    render_bento_grid(
        [
            metric_card("短线评分", f"{format_price(score.get('short_score'), 1)} / 100", "信号强度，不等于买入指令", "green" if sh_score >= 80 else "cyan", sh_indicator),
            metric_card("中长线评分", f"{format_price(score.get('long_score'), 1)} / 100", "趋势 + 财务/成长/估值" if score.get("fundamental_integrated") else "趋势代理 + 基本面待验证", "cyan", ln_indicator),
            metric_card("综合评级", rating, score.get("rating_explanation", ""), rating_tone, rating_indicator),
            metric_card("风险状态", risk_text, "风险控制分越高，技术风险越低", "green" if risk_control.get("score", 0) >= 10 else "orange", risk_indicator),
        ]
    )
    with st.container(border=True):
        st.markdown('<div class="chart-title"><span>评分含义说明</span><span class="pill pill-orange">仅供研究</span></div>', unsafe_allow_html=True)
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
            _render_chart_card("短线维度得分 / 满分", "条形图", plot_explainable_bar(short_breakdown, "短线维度得分"))
        with c2:
            _render_chart_card("短线得分率雷达", "雷达图", plot_score_radar(short_breakdown, "短线得分率"))
        c3, c4 = st.columns(2)
        with c3:
            _render_chart_card("短线贡献度", "瀑布图", plot_score_waterfall(short_breakdown, "短线贡献度"))
        with c4:
            _render_chart_card("短线扣分 / 缺口", "风险缺口", plot_risk_deductions(short_breakdown, "短线扣分 / 缺口"))
        render_dimension_cards(short_breakdown, "short")

    with tab_long:
        if score.get("fundamental_integrated"):
            st.info("中长线评分已纳入可获取的 ROE、ROA、D/E、收入/利润增长、PE/PB/PS 和股息率；DCF 仅在估值卡片中单独展示，不纳入评分。")
        else:
            st.warning("中长线评分主要基于价格趋势代理，财务和估值数据不足，因此不应单独作为中长期投资依据。")
        c1, c2 = st.columns(2)
        with c1:
            _render_chart_card("中长线维度得分 / 满分", "条形图", plot_explainable_bar(long_breakdown, "中长线维度得分"))
        with c2:
            _render_chart_card("中长线得分率雷达", "雷达图", plot_score_radar(long_breakdown, "中长线得分率"))
        c3, c4 = st.columns(2)
        with c3:
            _render_chart_card("中长线贡献度", "瀑布图", plot_score_waterfall(long_breakdown, "中长线贡献度"))
        with c4:
            _render_chart_card("中长线扣分 / 缺口", "风险缺口", plot_risk_deductions(long_breakdown, "中长线扣分 / 缺口"))
        render_dimension_cards(long_breakdown, "long")

    with tab_evidence:
        with st.container(border=True):
            st.markdown('<div class="chart-title"><span>底层数据证据</span><span class="pill pill-cyan">指标</span></div>', unsafe_allow_html=True)
            render_evidence_table(evidence)


def _render_analysis_dashboard(score: dict, hist: pd.DataFrame, report_path: str, dcf_assumptions: dict, fundamental_context: dict | None = None) -> None:
    latest = score.get("latest", {}) or {}
    warning = None
    ret_1d = latest.get("ret_1d")
    amount = latest.get("amount_est", latest.get("amount"))
    if amount is None and latest.get("close") is not None and latest.get("volume") is not None:
        amount = latest.get("close") * latest.get("volume")

    ret_tone, ret_indicator = _tone_from_number(ret_1d)
    short_tone = "green" if float(score.get("short_score", 0) or 0) >= 75 else "cyan" if float(score.get("short_score", 0) or 0) >= 60 else "orange"
    long_tone = "green" if float(score.get("long_score", 0) or 0) >= 65 else "cyan" if float(score.get("long_score", 0) or 0) >= 50 else "orange"

    price_label = "最新价"
    render_bento_grid(
        [
            metric_card(price_label, format_price(latest.get("close")), _dashboard_card_note(price_label, score, hist, amount), "cyan", _metric_indicator_key(price_label, score, hist, amount)),
            metric_card("当日涨跌幅", format_percent(ret_1d), _dashboard_card_note("当日涨跌幅", score, hist, amount), ret_tone, ret_indicator),
            metric_card("成交量", format_number_cn(latest.get("volume"), 2), _dashboard_card_note("成交量", score, hist, amount), "purple", _metric_indicator_key("成交量", score, hist, amount)),
            metric_card("估算成交额", format_number_cn(amount, 2), _dashboard_card_note("估算成交额", score, hist, amount), "blue", _metric_indicator_key("估算成交额", score, hist, amount)),
            metric_card("短线评分", format_price(score.get("short_score"), 1), _dashboard_card_note("短线评分", score, hist, amount), short_tone, _metric_indicator_key("短线评分", score, hist, amount)),
            metric_card("中长线评分", format_price(score.get("long_score"), 1), _dashboard_card_note("中长线评分", score, hist, amount), long_tone, _metric_indicator_key("中长线评分", score, hist, amount)),
        ]
    )

    # Dynamic badges for charts based on quantitative calculations
    close_val = float(latest.get("close", 0) or 0)
    ma20_val = float(latest.get("ma20", 0) or 0)
    ma60_val = float(latest.get("ma60", 0) or 0)
    if close_val > ma20_val > ma60_val:
        trend_badge = "多头排列 (偏强)"
    elif close_val < ma20_val < ma60_val:
        trend_badge = "空头排列 (偏弱)"
    elif close_val > ma20_val:
        trend_badge = "站上MA20 (反弹)"
    elif close_val < ma20_val:
        trend_badge = "跌破MA20 (整理)"
    else:
        trend_badge = "K线 + 均线"

    vol_ratio_val = float(latest.get("vol_ratio_20", 0) or 0)
    if vol_ratio_val >= 1.8:
        vol_badge = f"显著放量 ({vol_ratio_val:.2f}x)"
    elif vol_ratio_val >= 1.2:
        vol_badge = f"温和放量 ({vol_ratio_val:.2f}x)"
    elif vol_ratio_val > 0 and vol_ratio_val < 0.8:
        vol_badge = f"缩量运行 ({vol_ratio_val:.2f}x)"
    else:
        vol_badge = f"成交平稳 ({vol_ratio_val:.2f}x)"

    ret_1d_val = float(latest.get("ret_1d", 0) or 0)
    if ret_1d_val > 0 and vol_ratio_val >= 1.2:
        pv_badge = "量价齐升 (买盘强)"
    elif ret_1d_val < 0 and vol_ratio_val >= 1.2:
        pv_badge = "放量下跌 (抛压重)"
    elif ret_1d_val > 0 and vol_ratio_val < 0.8:
        pv_badge = "缩量上涨 (动量弱)"
    elif ret_1d_val < 0 and vol_ratio_val < 0.8:
        pv_badge = "缩量下跌 (正常整理)"
    else:
        pv_badge = "量价平衡"

    rsi_val = float(latest.get("rsi14", 0) or 0)
    if rsi_val >= 80:
        tech_badge = "RSI 超买 (警惕)"
    elif rsi_val <= 20:
        tech_badge = "RSI 超卖 (超跌)"
    elif rsi_val >= 55:
        tech_badge = "RSI 偏强震荡"
    elif rsi_val <= 45:
        tech_badge = "RSI 偏弱震荡"
    else:
        tech_badge = "RSI 中性整理"

    render_section_title("市场解读", "关键发现由价格结构、量能、动量指标和模型风险信号自动归纳。")
    render_insight_cards(_build_insights(score, hist, warning))

    render_section_title("核心图表", "图表替代表格成为主叙事：价格、成交量、量价关系与技术指标分层展示。")
    top_left, top_right = st.columns([1.45, 1])
    with top_left:
        _render_chart_card("价格趋势", trend_badge, plot_price_trend(hist))
    with top_right:
        _render_chart_card("成交量", vol_badge, plot_volume(hist))

    lower_left, lower_right = st.columns([1, 1])
    with lower_left:
        _render_chart_card("量价关系", pv_badge, plot_price_volume_scatter(hist), container_height=560)
    with lower_right:
        with st.container(border=True, height=560):
            st.markdown(f'<div class="chart-title"><span>技术指标</span><span class="pill pill-purple">{tech_badge}</span></div>', unsafe_allow_html=True)
            tab_rsi, tab_macd, tab_kdj = st.tabs(["RSI", "MACD", "KDJ"])
            with tab_rsi:
                st.plotly_chart(plot_rsi(hist), use_container_width=True, config={"displayModeBar": False})
            with tab_macd:
                st.plotly_chart(plot_macd(hist), use_container_width=True, config={"displayModeBar": False})
            with tab_kdj:
                st.plotly_chart(plot_kdj(hist), use_container_width=True, config={"displayModeBar": False})

    dashboard_code = str(
        score.get("code")
        or ((fundamental_context or {}).get("payload", {}) or {}).get("profile", {}).get("code")
        or ""
    )
    if fundamental_context is None and dashboard_code:
        fundamental_context = _build_fundamental_context(dashboard_code, hist, score, dcf_assumptions)
    if fundamental_context:
        score = _enrich_score_with_fundamentals(score, fundamental_context)
    fundamental_context = _render_fundamental_snapshot(score.get("code") or dashboard_code, hist, score, dcf_assumptions, fundamental_context)

    _render_explainable_scoring(score)

    render_section_title("近期行情数据", "默认只展示最近 10 条，可读性优先；完整原始数据在折叠区。")
    with st.container(border=True):
        render_recent_data_table(hist, rows=10)

    with st.container(border=True):
        st.markdown('<div class="chart-title"><span>报告输出</span><span class="pill pill-cyan">已保存</span></div>', unsafe_allow_html=True)
        st.success(f"分析报告已保存：{report_path}")
        st.write(score.get("summary"))


def _fmt_count(value) -> str:
    try:
        return str(int(float(value)))
    except Exception:
        return "-"


def _sent_num(value, default: float | None = None) -> float | None:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _sentiment_tone(value: float | None) -> str:
    value = _sent_num(value)
    if value is None:
        return "watch"
    if value >= 70:
        return "danger"
    if value >= 55:
        return "warning"
    if value >= 40:
        return "watch"
    return "cool"


def _semantic_tone(value: float | None, bands: tuple[float, float, float], higher_is_risk: bool = False) -> tuple[str, str]:
    value = _sent_num(value)
    if value is None:
        return "缺失", "neutral"
    low, mid, high = bands
    if higher_is_risk:
        if value >= high:
            return "高风险", "danger"
        if value >= mid:
            return "偏高", "warning"
        if value >= low:
            return "分歧", "watch"
        return "健康", "good"
    if value >= high:
        return "过热", "danger"
    if value >= mid:
        return "活跃", "good"
    if value >= low:
        return "常态", "watch"
    return "低迷", "cool"


def _sentiment_metric_card(label: str, value: str, raw_value: float | None, note: str, status: str, tone: str, *, percent: bool = False, cap: float = 100, delta: float | None = None) -> str:
    raw = _sent_num(raw_value, 0) or 0
    scale_value = raw * 100 if percent else raw
    denominator = cap * 100 if percent else cap
    pct = max(0, min(100, scale_value / max(denominator, 1) * 100))
    delta_html = ""
    if delta is not None:
        delta_tone = "up" if delta >= 0 else "down"
        delta_html = f'<em class="sentiment-delta {delta_tone}">环比 {delta:+.1f}</em>'
    return (
        f'<div class="sentiment-metric-card {tone}">'
        f'<div class="sentiment-metric-top"><span>{escape(label)}</span><b>{escape(status)}</b></div>'
        f'<strong>{escape(value)}</strong>'
        f'<div class="semantic-meter"><i style="width:{pct:.1f}%"></i></div>'
        f'<div class="semantic-scale"><span>低</span><span>中</span><span>高</span></div>'
        f'<p>{escape(note)}</p>{delta_html}'
        f'</div>'
    )


def _render_sentiment_metric_grid(metrics: dict, history: pd.DataFrame) -> None:
    prev = history.iloc[-2].to_dict() if history is not None and len(history) >= 2 else {}
    emotion = _sent_num(metrics.get("emotion_score"))
    broken = _sent_num(metrics.get("broken_rate"))
    prev_premium = _sent_num(metrics.get("prev_limit_premium"))
    max_streak = _sent_num(metrics.get("max_streak"))
    short_emotion = _sent_num(metrics.get("short_emotion"))
    loss_effect = _sent_num(metrics.get("loss_effect"))
    big_market = _sent_num(metrics.get("big_market_factor"))
    divergence = _sent_num(metrics.get("divergence"))

    emotion_status, emotion_tone = _semantic_tone(emotion, (35, 55, 70))
    broken_status, broken_tone = _semantic_tone((broken or 0) * 100, (15, 25, 35), higher_is_risk=True)
    premium_status, premium_tone = ("承接强", "good") if (prev_premium or 0) > 8 else ("承接弱", "warning") if (prev_premium or 0) < 0 else ("平稳溢价", "watch")
    streak_status, streak_tone = ("高标强", "danger") if (max_streak or 0) >= 7 else ("空间打开", "good") if (max_streak or 0) >= 4 else ("空间低", "watch")

    core_cards = [
        _sentiment_metric_card("情绪综合指数", format_price(emotion, 1), emotion, "55 以上才算转强，70 以上开始警惕一致过热。", emotion_status, emotion_tone, delta=_sent_num(metrics.get("emotion_score"), 0) - _sent_num(prev.get("emotion_score"), 0) if prev else None),
        _sentiment_metric_card("炸板率", format_percent(broken), broken, "25% 以上代表分歧明显，35% 以上是高风险区。", broken_status, broken_tone, percent=True, cap=0.4),
        _sentiment_metric_card("昨日涨停溢价", format_percent(prev_premium / 100 if prev_premium is not None else None), prev_premium, "正值说明昨日涨停承接仍在，负值代表接力退潮。", premium_status, premium_tone, cap=30),
        _sentiment_metric_card("连板空间高度", f"{_fmt_count(max_streak)}板", max_streak, "4 板以上空间打开，7 板以上进入高位一致风险区。", streak_status, streak_tone, cap=10),
    ]
    st.markdown('<div class="sentiment-metric-grid core">' + "".join(core_cards) + "</div>", unsafe_allow_html=True)

    short_status, short_tone = _semantic_tone(short_emotion, (35, 55, 70))
    loss_status, loss_tone = _semantic_tone(loss_effect, (25, 45, 65), higher_is_risk=True)
    big_status, big_tone = _semantic_tone(big_market, (42, 55, 68))
    div_status, div_tone = _semantic_tone(divergence, (20, 35, 55), higher_is_risk=True)
    secondary_cards = [
        _sentiment_metric_card("短线情绪", format_price(short_emotion, 1), short_emotion, "反映涨停高度和短线承接，低于 40 不适合追高。", short_status, short_tone),
        _sentiment_metric_card("亏钱效应", format_price(loss_effect, 1), loss_effect, "越高说明跌停、炸板和下跌扩散越严重。", loss_status, loss_tone),
        _sentiment_metric_card("大盘宽度", format_price(big_market, 1), big_market, "由上涨家数占比折算，低于 45 说明指数或个股扩散不足。", big_status, big_tone),
        _sentiment_metric_card("三维分歧度", format_price(divergence, 1), divergence, "大盘、超短和炸板率分歧越高，越需要控仓。", div_status, div_tone),
    ]
    st.markdown('<div class="sentiment-metric-grid secondary">' + "".join(secondary_cards) + "</div>", unsafe_allow_html=True)


def _render_market_signal_verification(payload: dict) -> None:
    signal_payload = payload.get("a_stock_market_signal", {}) or {}
    cards = signal_payload.get("cards", []) or []
    render_section_title("主线与资金验证", "同花顺热点、北向资金、龙虎榜、行业轮动和指数 ETF 风险偏好。")
    if not cards:
        with st.container(border=True):
            st.info("当前 a-stock-data 市场信号暂未生成，市场情绪仍使用涨跌停生态与板块梯队。")
        return
    html_cards = []
    for card in cards:
        tone_map = {"green": "good", "cyan": "watch", "blue": "watch", "purple": "watch", "orange": "warning", "red": "danger"}
        tone = tone_map.get(str(card.get("tone") or "cyan"), "watch")
        html_cards.append(
            _sentiment_metric_card(
                str(card.get("label") or "-"),
                str(card.get("value") or "N/A"),
                _sent_num(card.get("score"), 0),
                f"{card.get('decision_note', '')} 阈值：{card.get('threshold_note', '')} 来源：{card.get('source', '-')}",
                str(card.get("level") or "待判断"),
                tone,
                cap=100,
            )
        )
    st.markdown('<div class="sentiment-metric-grid secondary">' + "".join(html_cards) + "</div>", unsafe_allow_html=True)
    details = signal_payload.get("details", {}) or {}
    with st.expander("a-stock-data 市场信号明细", expanded=False):
        tabs = st.tabs(["热点", "龙虎榜", "行业"])
        with tabs[0]:
            hot = details.get("hot_reason")
            if isinstance(hot, pd.DataFrame) and not hot.empty:
                render_glass_dataframe(hot.head(80), height=520)
            else:
                st.info("暂无热点明细。")
        with tabs[1]:
            lhb = details.get("daily_dragon_tiger")
            if isinstance(lhb, pd.DataFrame) and not lhb.empty:
                render_glass_dataframe(lhb.head(80), height=520)
            else:
                st.info("暂无全市场龙虎榜明细。")
        with tabs[2]:
            industry = details.get("industry")
            if isinstance(industry, pd.DataFrame) and not industry.empty:
                render_glass_dataframe(industry.head(80), height=520)
            else:
                st.info("暂无行业轮动明细。")


def _sentiment_data_status_label(data_quality: str | None) -> str:
    status = str(data_quality or "OK")
    if status == "OK":
        return "OK"
    if "市场宽度" in status or "板块资金" in status:
        return "有缺口"
    return "缓存中"


def _format_money_yi(value) -> str:
    value = _sent_num(value)
    if value is None:
        return "-"
    return f"{value / 100000000:.1f}亿"


def _command_label(text: str) -> None:
    st.markdown(f'<div class="command-field-label">{escape(text)}</div>', unsafe_allow_html=True)


def _set_window_selection(key: str, option: int, date_key: str | None = None) -> None:
    st.session_state[key] = int(option)
    if date_key:
        st.session_state[date_key] = _start_date_for_trading_days(int(option)).date()


def _window_buttons(
    key: str,
    current: int,
    options: tuple[int, ...] = (14, 30, 60),
    date_key: str | None = None,
) -> int:
    if key not in st.session_state:
        st.session_state[key] = int(current)
    selected = int(st.session_state.get(key, current) or current)
    cols = st.columns(len(options), gap="small")
    for col, option in zip(cols, options):
        with col:
            active = selected == option
            st.button(
                f"近{option}日",
                key=f"{key}_{option}",
                use_container_width=True,
                type="primary" if active else "secondary",
                on_click=_set_window_selection,
                args=(key, option, date_key),
            )
    return int(st.session_state.get(key, selected) or selected)


def _render_sentiment_conclusion(payload: dict) -> None:
    metrics = payload.get("metrics", {})
    tactics = payload.get("tactics", {})
    period = metrics.get("period", "待确认")
    main_line = tactics.get("main_line") or metrics.get("top_board") or "暂无主线"
    mismatch = "、".join(tactics.get("mismatch", [])[:3])
    timeline = tactics.get("timeline", [])
    timeline_html = "".join(
        f'<div class="sentiment-time-row"><strong>{escape(str(item.get("time", "")))}</strong><span>{escape(str(item.get("action", "")))}</span></div>'
        for item in timeline
    )
    score_text = format_price(metrics.get("emotion_score"), 1)
    _, tone = _semantic_tone(_sent_num(metrics.get("emotion_score")), (35, 55, 70))
    st.markdown(
        f"""
        <section class="sentiment-command-strip {escape(tone)}">
          <div>
            <div class="sentiment-kicker">数据日期：{escape(str(payload.get("trade_date", "-")))} · 最后更新：{escape(str(payload.get("updated_at", "-")))}</div>
            <div class="sentiment-headline">{escape(str(period))}</div>
            <div class="sentiment-subline">情绪综合指数 <span class="sentiment-score">{escape(score_text)}</span> · 主线方向 {escape(str(main_line))} · {escape(str(metrics.get("suggestion", "")))}</div>
          </div>
          <div class="sentiment-plan-grid">
            <div><span>激进型</span><strong>{escape(str(tactics.get("aggressive_position", "-")))}</strong></div>
            <div><span>稳健型</span><strong>{escape(str(tactics.get("stable_position", "-")))}</strong></div>
            <div><span>战术风格</span><strong>{escape(mismatch or "等待确认")}</strong></div>
          </div>
          <div class="sentiment-timeline">{timeline_html}</div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _render_index_monitor(payload: dict) -> None:
    indices = payload.get("indices", pd.DataFrame())
    breadth = payload.get("breadth", {}) or {}
    if indices is None or indices.empty:
        return
    cards = []
    for _, row in indices.head(7).iterrows():
        pct = _num(row.get("pct"))
        cls = "sentiment-index-up" if pct and pct > 0 else "sentiment-index-down" if pct and pct < 0 else ""
        cards.append(
            f'<div class="sentiment-index-card {cls}">'
            f'<span>{escape(str(row.get("name") or "-"))}</span>'
            f'<strong>{format_price(row.get("price"), 2)}</strong>'
            f'<em>{f"{pct:+.2f}%" if pct is not None else "待获取"}</em>'
            f'</div>'
        )
    up = breadth.get("up")
    down = breadth.get("down")
    st.markdown(
        '<div class="sentiment-index-grid">' + "".join(cards) + "</div>",
        unsafe_allow_html=True,
    )
    with st.container(border=True):
        st.markdown(
            f'<div class="chart-title"><span>大盘诊断</span><span class="pill pill-cyan">{escape(str(breadth.get("source", "公共源")))}</span></div>',
            unsafe_allow_html=True,
        )
        if breadth.get("available"):
            st.caption(f"市场宽度：上涨 {up} / 下跌 {down}，两市成交额 {_format_money_yi(breadth.get('amount'))}。")
        else:
            st.caption("市场宽度暂按指数和涨跌停生态代理估算，等待公共行情源恢复后自动切回全市场宽度。")


def _render_board_ladder(boards: pd.DataFrame, board_members: pd.DataFrame | None = None) -> None:
    if boards is None or boards.empty:
        st.info("当前未获取到板块梯队，页面将只展示涨跌停生态。")
        return
    cards = []
    max_strength = max(float(pd.to_numeric(boards.get("strength", pd.Series([1])), errors="coerce").max() or 1), 1)
    for _, row in boards.head(8).iterrows():
        width = max(8, min(100, float(row.get("strength") or 0) / max_strength * 100))
        tone = "danger" if width >= 75 else "good" if width >= 60 else "watch" if width >= 40 else "cool"
        pct_rank = "前排" if width >= 72 else "中段" if width >= 40 else "后排"
        cards.append(
            f'<div class="sentiment-board-card {tone}">'
            f'<div>'
            f'  <div><strong>{escape(str(row.get("board_name") or "-"))}</strong><span>{escape(str(row.get("role") or "观察"))}</span></div>'
            f'  <b class="text-{tone}">{width:.0f}%</b>'
            f'</div>'
            f'<p>涨停 {_fmt_count(row.get("limit_count"))} · 炸板 {_fmt_count(row.get("broken_count"))} · 最高 {_fmt_count(row.get("max_streak"))}板</p>'
            f'<div class="sentiment-strength {tone}"><i style="width:{width:.1f}%"></i></div>'
            f'<small>{pct_rank}强度 · {escape(str(row.get("evidence") or ""))}<br>强度 {format_price(row.get("strength"), 1)} · {escape(str(row.get("strategy") or ""))}</small>'
            f'</div>'
        )
    st.markdown('<div class="sentiment-board-grid">' + "".join(cards) + "</div>", unsafe_allow_html=True)
    if board_members is not None and not board_members.empty:
        with st.expander("查看板块对应个股明细", expanded=False):
            options = boards.head(20)["board_name"].dropna().astype(str).tolist()
            selected = st.selectbox("板块", options, key="sentiment_board_detail_select")
            detail = board_members[board_members.get("industry", pd.Series(dtype=str)).astype(str) == selected].copy()
            render_glass_dataframe(_format_board_member_table(detail, 80), height=520)


def _format_pool_table(df: pd.DataFrame, limit: int = 12) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    view = df.head(limit).copy()
    keep = [col for col in ["name", "code", "industry", "pct", "turnover", "amount", "limit_streak", "first_limit_time", "break_count", "reason"] if col in view.columns]
    view = view[keep].rename(
        columns={
            "name": "名称",
            "code": "代码",
            "industry": "题材",
            "pct": "涨跌幅",
            "turnover": "换手率",
            "amount": "成交额",
            "limit_streak": "连板",
            "first_limit_time": "首次封板",
            "break_count": "炸板/开板",
            "reason": "入选理由",
        }
    )
    for col in ["涨跌幅", "换手率"]:
        if col in view.columns:
            view[col] = pd.to_numeric(view[col], errors="coerce").map(lambda x: "N/A" if pd.isna(x) else f"{x:.2f}%")
    if "成交额" in view.columns:
        view["成交额"] = pd.to_numeric(view["成交额"], errors="coerce").map(lambda x: "N/A" if pd.isna(x) else format_number_cn(x))
    return view


def _format_board_member_table(df: pd.DataFrame, limit: int = 80) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    view = df.head(limit).copy()
    keep = [col for col in ["member_type", "name", "code", "pct", "limit_streak", "first_limit_time", "last_limit_time", "break_count", "turnover", "amount", "reason"] if col in view.columns]
    view = view[keep].rename(
        columns={
            "member_type": "类型",
            "name": "名称",
            "code": "代码",
            "pct": "涨跌幅",
            "limit_streak": "连板",
            "first_limit_time": "首次封板",
            "last_limit_time": "最后封板",
            "break_count": "炸板/开板",
            "turnover": "换手率",
            "amount": "成交额",
            "reason": "入选理由",
        }
    )
    for col in ["涨跌幅", "换手率"]:
        if col in view.columns:
            view[col] = pd.to_numeric(view[col], errors="coerce").map(lambda x: "N/A" if pd.isna(x) else f"{x:.2f}%")
    if "成交额" in view.columns:
        view["成交额"] = pd.to_numeric(view["成交额"], errors="coerce").map(lambda x: "N/A" if pd.isna(x) else format_number_cn(x))
    return view


def _render_battlefield(tactics: dict) -> None:
    cards = []
    for item in tactics.get("battlefield", []):
        score = _sent_num(item.get("score"), 0) or 0
        width = max(5, min(100, score))
        tone = "danger" if score >= 75 else "good" if score >= 60 else "watch" if score >= 40 else "cool"
        status = "强机会/高波动" if score >= 75 else "可参与" if score >= 60 else "观察" if score >= 40 else "偏弱"
        cards.append(
            f'<div class="sentiment-method-card {tone}">'
            f'<span>{escape(str(item.get("tag", "观察")))}</span>'
            f'<strong>{escape(str(item.get("name", "-")))}</strong>'
            f'<b>{score:.1f}%</b>'
            f'<div class="sentiment-strength {tone}"><i style="width:{width:.1f}%"></i></div>'
            f'<small>{status}</small>'
            f'<p>{escape(str(item.get("note", "")))}</p>'
            f'</div>'
        )
    st.markdown('<div class="sentiment-method-grid">' + "".join(cards) + "</div>", unsafe_allow_html=True)


def _render_watchlist_table(watchlist: pd.DataFrame) -> None:
    if watchlist is None or watchlist.empty:
        st.info("当前未生成观察池。")
        return
    view = watchlist[[col for col in ["name", "code", "industry", "limit_streak", "first_limit_time", "break_count", "buy_condition", "risk_note", "priority"] if col in watchlist.columns]].rename(
        columns={
            "name": "标的",
            "code": "代码",
            "industry": "题材",
            "limit_streak": "连板",
            "first_limit_time": "首次封板",
            "break_count": "炸板次数",
            "buy_condition": "买点条件",
            "risk_note": "风控提示",
            "priority": "优先级",
        }
    )
    render_glass_dataframe(view, height=min(420, 44 + len(view) * 42))


def _render_metric_explanations(metrics: dict) -> None:
    rows = metrics.get("explanations", []) or []
    with st.expander("核心指标的数据依据与公式", expanded=False):
        if not rows:
            st.info("当前未生成指标解释。")
            return
        view = pd.DataFrame(rows)
        if "当前值" in view.columns:
            view["当前值"] = view["当前值"].map(lambda x: format_percent(x) if isinstance(x, float) and abs(x) <= 1 else format_price(x, 2) if _sent_num(x) is not None else "-")
        render_glass_dataframe(view, height=min(520, 64 + len(view) * 70))


def _render_market_sentiment_dashboard(payload: dict, window_days: int) -> None:
    metrics = payload.get("metrics", {})
    latest = payload.get("latest", {})
    tactics = payload.get("tactics", {})
    render_section_title("市场情绪仪表盘", "全市场情绪、涨停生态、板块梯队和次日观察池。")
    _render_sentiment_conclusion(payload)
    _render_index_monitor(payload)

    _render_sentiment_metric_grid(metrics, payload.get("history", pd.DataFrame()))
    _render_market_signal_verification(payload)
    _render_metric_explanations(metrics)

    st.markdown('<div class="chart-title" style="margin-bottom:16px;"><span>情绪周期定位</span><span class="pill pill-cyan">综合研判</span></div>', unsafe_allow_html=True)
    _render_emotion_cycle_position(metrics)

    st.markdown("<div style='margin-bottom: 24px;'></div>", unsafe_allow_html=True)

    # 5日图表并排展示
    hist_df = payload.get("history", pd.DataFrame())
    emo_badge, emo_class = analyze_recent_5d_emotion(hist_df)
    counts_badge, counts_class = analyze_recent_5d_limit_counts(hist_df)
    amt_badge, amt_class = analyze_recent_5d_amount(hist_df)

    c1, c2, c3 = st.columns(3)
    with c1:
        _render_chart_card("近5日情绪评分", emo_badge, plot_recent_5d_emotion(hist_df), pill_class=emo_class)
    with c2:
        _render_chart_card("近5日涨跌停家数", counts_badge, plot_recent_5d_limit_counts(hist_df), pill_class=counts_class)
    with c3:
        _render_chart_card("近5日接力成交额", amt_badge, plot_recent_5d_amount(hist_df), pill_class=amt_class)

    st.markdown("<div style='margin-bottom: 32px;'></div>", unsafe_allow_html=True)

    st.markdown('<div class="chart-title"><span>板块梯队复盘</span><span class="pill pill-cyan">市场合力</span></div>', unsafe_allow_html=True)
    _render_board_ladder(payload.get("boards", pd.DataFrame()), payload.get("board_members", pd.DataFrame()))

    st.markdown('<div class="chart-title" style="margin-top:48px;"><span>赚钱手法分析</span><span class="pill pill-cyan">胜率估算</span></div>', unsafe_allow_html=True)
    _render_battlefield(tactics)

    risk = tactics.get("risk", {})
    chance = tactics.get("chance", {})
    col_risk, col_chance = st.columns(2)
    with col_risk:
        st.markdown(
            f'<div class="sentiment-alert risk"><strong>明日风险 Checklist</strong><span>{escape(str(risk.get("level", "-")))}</span><p>{escape(str(risk.get("title", "")))}</p><small>{escape(str(risk.get("detail", "")))}</small></div>',
            unsafe_allow_html=True,
        )
    with col_chance:
        st.markdown(
            f'<div class="sentiment-alert chance"><strong>明日机会 Watchlist</strong><span>{escape(str(chance.get("grade", "-")))}</span><p>{escape(str(chance.get("title", "")))}</p><small>{escape(str(chance.get("detail", "")))}</small></div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div class="chart-title" style="margin-top:24px;"><span>明日观察池</span><span class="pill pill-cyan">候选标的</span></div>', unsafe_allow_html=True)
    _render_watchlist_table(payload.get("watchlist", pd.DataFrame()))

    st.markdown("<div style='margin-bottom: 48px;'></div>", unsafe_allow_html=True)

    # 纵向排列两个大图表
    history_for_detail = payload.get("history", pd.DataFrame())
    valid_history_days = 0
    if history_for_detail is not None and not history_for_detail.empty:
        counts = (
            pd.to_numeric(history_for_detail.get("limit_up_count", 0), errors="coerce").fillna(0)
            + pd.to_numeric(history_for_detail.get("broken_count", 0), errors="coerce").fillna(0)
            + pd.to_numeric(history_for_detail.get("limit_down_count", 0), errors="coerce").fillna(0)
            + pd.to_numeric(history_for_detail.get("strong_count", 0), errors="coerce").fillna(0)
        )
        missing = pd.to_numeric(history_for_detail.get("history_missing", 0), errors="coerce").fillna(0)
        valid_history_days = int(((counts > 0) & (missing <= 0)).sum())
    render_section_title("情绪周期三维监控 (细节展开)", f"观察窗口近 {window_days} 日，当前公共源补齐到 {valid_history_days} 个有效交易日；空池日不再绘制为假 0 值。")
    _render_chart_card("三维指标趋势", f"近{window_days}日", plot_market_sentiment_cycle(payload.get("history", pd.DataFrame())))
    st.markdown("<div style='margin-bottom: 24px;'></div>", unsafe_allow_html=True)
    _render_chart_card("涨跌停生态", "近20日", plot_limit_ecology(payload.get("history", pd.DataFrame())))

    _render_chart_card("板块情绪热力分布图", "分位热度", plot_market_sentiment_heatmap(payload.get("heatmap", pd.DataFrame())))

    tabs = st.tabs(["涨停池", "炸板池", "跌停池", "强势股池", "数据源诊断"])
    with tabs[0]:
        render_glass_dataframe(_format_pool_table(latest.get("limit_up", pd.DataFrame()), 20), height=520)
    with tabs[1]:
        render_glass_dataframe(_format_pool_table(latest.get("broken", pd.DataFrame()), 20), height=520)
    with tabs[2]:
        render_glass_dataframe(_format_pool_table(latest.get("limit_down", pd.DataFrame()), 20), height=520)
    with tabs[3]:
        render_glass_dataframe(_format_pool_table(latest.get("strong", pd.DataFrame()), 30), height=560)
    with tabs[4]:
        warnings = payload.get("warnings", []) or []
        if warnings:
            render_glass_dataframe(pd.DataFrame([w if isinstance(w, dict) else {"message": str(w)} for w in warnings[:60]]), height=420)
        else:
            st.success("本轮没有记录到数据源错误。")

        st.markdown("<div style='margin-top: 32px; margin-bottom: 16px; border-top: 1px solid rgba(255,255,255,0.08); padding-top: 24px;'></div>", unsafe_allow_html=True)
        st.markdown('<div class="chart-title"><span>缓存与数据生命周期管理</span><span class="pill pill-orange">系统级操作</span></div>', unsafe_allow_html=True)

        col_info, col_btn = st.columns([0.76, 0.24], vertical_alignment="center")
        with col_info:
            st.markdown(
                '<div style="color: var(--text-muted, #A7ADBA); font-size: 0.9rem; line-height: 1.5;">'
                '系统目前缓存了包括价格序列、公开新闻快讯、龙虎榜公告以及基本面分析等各类多源数据以保证极速加载体验。'
                '如果遇到数据接口获取异常、数据偏差或想要即刻同步最新数据，您可以使用右侧的一键清空缓存操作。'
                '</div>',
                unsafe_allow_html=True
            )
        with col_btn:
            if st.button("一键清除所有缓存", key="btn_clear_global_cache", type="primary", use_container_width=True):
                try:
                    cache_stats = FileCache().clear_cache()
                    total_cleared = sum(cache_stats.values())
                    st.toast(f"✨ 缓存清空成功！共释放了 {total_cleared} 个文件", icon="✅")
                    st.success(
                        f"**成功清理以下数据接口缓存：**  \n"
                        f"📁 价格数据: {cache_stats.get('price', 0)} 个 | "
                        f"📁 财务基本面: {cache_stats.get('fundamentals', 0)} 个 | "
                        f"📁 公开新闻: {cache_stats.get('news', 0)} 个  \n"
                        f"📁 行业题材: {cache_stats.get('industry', 0)} 个 | "
                        f"📁 错误日志: {cache_stats.get('logs', 0)} 个"
                    )
                except Exception as ex:
                    st.error(f"清除缓存失败：{ex}")


def _render_ai_market_dashboard(config: dict) -> None:
    provider_options = ["Gemini", "DeepSeek"]
    selected_label = st.segmented_control(
        "AI模型",
        provider_options,
        default=st.session_state.get("ai_market_provider_label", "DeepSeek"),
        key="ai_market_provider_label",
        label_visibility="collapsed",
    )
    provider = "deepseek" if selected_label == "DeepSeek" else "gemini"
    st.markdown(f'<div id="jocket-ai-provider" data-provider="{escape(str(selected_label))}"></div>', unsafe_allow_html=True)
    assistant = AIMarketAssistant(config, provider=provider)
    if "ai_market_messages" not in st.session_state:
        st.session_state["ai_market_messages"] = []
    has_pending_prompt = bool(st.session_state.get("pending_prompt"))
    if not has_pending_prompt:
        st.session_state["ai_market_processing"] = False
    is_processing = bool(st.session_state.get("ai_market_processing") or has_pending_prompt)
    st.markdown(
        f'<div id="jocket-ai-processing" data-running="{str(is_processing).lower()}"></div>',
        unsafe_allow_html=True,
    )

    def render_ai_message(role: str, content: str) -> None:
        role_class = "user" if role == "user" else "assistant"
        label = "你" if role_class == "user" else "AI洞察"
        safe_content = markdown.markdown(str(content or ""), extensions=['fenced_code', 'tables', 'nl2br'])
        st.markdown(
            f"""
            <div class="ai-message-row {role_class}">
              <div class="ai-message-avatar">{escape(label[:2])}</div>
              <div class="ai-message-bubble">
                <div class="ai-message-name">{escape(label)}</div>
                <div class="ai-message-content">{safe_content}</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if st.session_state.get("pending_prompt"):
        prompt_text = st.session_state.pop("pending_prompt")
        keywords = st.session_state.pop("pending_keywords", DEFAULT_MARKET_KEYWORDS)
        forced_skills_pending = st.session_state.pop("pending_forced_skills", [])

        st.session_state["ai_market_messages"].append({"role": "user", "content": prompt_text})
        st.session_state["ai_market_processing"] = True

        with st.container(height=600, border=False):
            st.markdown('<section class="ai-thread">', unsafe_allow_html=True)
            placeholder = st.empty()
            for message in reversed(st.session_state["ai_market_messages"]):
                render_ai_message(message["role"], message["content"])
            st.markdown("</section>", unsafe_allow_html=True)

            full_answer = ""
            safe_content = markdown.markdown("I'm Jocketing... 正在检索多维行情数据 ▌", extensions=['fenced_code', 'tables', 'nl2br'])
            placeholder.markdown(
                f"""
                <div class="ai-message-row assistant">
                  <div class="ai-message-avatar">AI</div>
                  <div class="ai-message-bubble">
                    <div class="ai-message-name">AI洞察</div>
                    <div class="ai-message-content">{safe_content}</div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if not assistant.ready():
                full_answer = f"未检测到 {assistant.provider_label()} API token。请配置后重试。"
                safe_content = markdown.markdown(full_answer, extensions=['fenced_code', 'tables', 'nl2br'])
                placeholder.markdown(
                    f"""
                    <div class="ai-message-row assistant">
                      <div class="ai-message-avatar">AI</div>
                      <div class="ai-message-bubble">
                        <div class="ai-message-name">AI洞察</div>
                        <div class="ai-message-content">{safe_content}</div>
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                try:
                    context = assistant.context_snapshot(prompt_text, st.session_state["ai_market_messages"][:-1], keywords, forced_skills_pending)

                    pro_keywords = ["深度", "逻辑", "分析", "研究", "估值", "基本面", "财报", "资金", "怎么看", "为什么"]
                    use_pro = any(kw in prompt_text for kw in pro_keywords) or (len(str(context.get("alphaear_stock", ""))) > 100)

                    if assistant.settings.provider == "deepseek":
                        model_override = assistant.deepseek_model_for(use_pro)
                    else:
                        model_override = "gemini-2.5-pro" if use_pro else "gemini-2.5-flash"

                    messages = assistant._build_messages(prompt_text, st.session_state["ai_market_messages"][:-1], context)

                    for chunk in assistant._ask_model_stream(messages, model_override=model_override):
                        full_answer += chunk
                        safe_content = markdown.markdown(full_answer + " ▌", extensions=['fenced_code', 'tables', 'nl2br'])
                        placeholder.markdown(
                            f"""
                            <div class="ai-message-row assistant">
                              <div class="ai-message-avatar">AI</div>
                              <div class="ai-message-bubble">
                                <div class="ai-message-name">AI洞察</div>
                                <div class="ai-message-content">{safe_content}</div>
                              </div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                except Exception as e:
                    full_answer += f"\n\n**流式输出发生异常:** {e}"

            if not full_answer:
                full_answer = "模型没有返回有效内容。"

            safe_content = markdown.markdown(full_answer, extensions=['fenced_code', 'tables', 'nl2br'])
            placeholder.markdown(
                f"""
                <div class="ai-message-row assistant">
                  <div class="ai-message-avatar">AI</div>
                  <div class="ai-message-bubble">
                    <div class="ai-message-name">AI洞察</div>
                    <div class="ai-message-content">{safe_content}</div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.session_state["ai_market_messages"].append({"role": "assistant", "content": full_answer})
            st.session_state["ai_market_processing"] = False
            st.rerun()

    elif not st.session_state["ai_market_messages"]:
        st.markdown(
            f"""
            <section class="ai-empty-state ai-chat-shell">
              <div class="ai-chat-shell-inner" style="position: relative; display: flex; flex-direction: column; align-items: center; justify-content: center; width: 100%;">
                <div class="ai-breathing-orb"></div>
                <div class="ai-chat-shell-text" style="display: flex; flex-direction: column; align-items: center; justify-content: center; z-index: 1;">
                  <h1>今天想看什么行情？</h1>
                  <p>询问市场主线、板块催化、个股消息面或盘前观察清单。</p>
                  <div class="ai-provider-line" style="margin-top: 10px;">{escape(assistant.provider_label())} · {"已连接" if assistant.ready() else "未配置"}</div>
                </div>
              </div>
            </section>
            """,
            unsafe_allow_html=True,
        )
    else:
        with st.container(height=600, border=False):
            st.markdown('<section class="ai-thread">', unsafe_allow_html=True)
            for message in reversed(st.session_state["ai_market_messages"]):
                render_ai_message(message["role"], message["content"])
            st.markdown("</section>", unsafe_allow_html=True)


st.markdown('<div class="product-masthead"><span>Jocket</span></div>', unsafe_allow_html=True)
page = st.segmented_control(
    "核心功能",
    ["AI洞察", "个股行情", "市场情绪", "投研分析"],
    default="AI洞察",
    key="analysis_mode_top",
    label_visibility="collapsed",
)
if page is None:
    page = "AI洞察"
st.markdown(f'<div id="jocket-current-page" data-page="{escape(str(page))}"></div>', unsafe_allow_html=True)
_mode_info = {
    "AI洞察": ("AI洞察", "询问大盘主线、板块催化或个股消息面，获取结合最新信号的深度研判。"),
    "个股行情": ("个股行情", "输入股票代码或名称后运行，系统会自动生成趋势评级、量价证据、基本面与消息面研究视图。"),
    "市场情绪": ("市场情绪", "复盘全市场涨停生态、情绪周期、板块梯队和次日条件观察池。"),
    "投研分析": ("深度投研", "多智能体协作完成高质量A股研报分析，提供全面的个股深度剖析。"),
}
config.setdefault("data", {})["provider"] = "auto"

code = ""
name = ""
dcf_years = 5
dcf_growth = 5.0
dcf_terminal_growth = 2.0
dcf_discount = 10.0
dcf_margin = 20.0
sentiment_window = 60
_now = pd.Timestamp.now(tz="Asia/Shanghai").tz_localize(None)
if _now.dayofweek < 5:
    sentiment_default_date = _now.normalize().date()
else:
    sentiment_default_date = (_now.normalize() - pd.offsets.BDay(1)).date()
previous_sentiment_default = st.session_state.get("sentiment_default_trade_date")
current_sentiment_state = st.session_state.get("sentiment_date")
if previous_sentiment_default is None or current_sentiment_state in {None, previous_sentiment_default}:
    st.session_state.pop("sentiment_date", None)
    sentiment_date = sentiment_default_date
else:
    sentiment_date = current_sentiment_state
st.session_state["sentiment_default_trade_date"] = sentiment_default_date
sentiment_refresh = False
sentiment_backfill = False
run = False
ai_prompt = ""
ai_submitted = False
ai_forced_skills = []
AI_SKILL_BUTTONS = [
    ("alphaear-news", "实时财经新闻与热点趋势"),
    ("alphaear-stock", "A股/港股/美股行情与基本面"),
    ("alphaear-sentiment", "FinBERT / LLM 情感分析"),
    ("alphaear-predictor", "Kronos 时序预测模型，结合新闻情绪动态调整"),
    ("alphaear-signal-tracker", "投资信号演化追踪"),
    ("alphaear-logic-visualizer", "传导链路图生成"),
    ("alphaear-reporter", "专业研报生成"),
    ("alphaear-search", "全网搜索与本地 RAG"),
    ("qqqq", "QQQ 量化回测、策略胜率、支撑压力与交易计划"),
]

if page == "AI洞察":
    def _queue_ai_market_prompt():
        prompt = st.session_state.get("ai_market_prompt", "").strip()
        if prompt:
            st.session_state["pending_prompt"] = prompt
            st.session_state["pending_keywords"] = DEFAULT_MARKET_KEYWORDS
            st.session_state["pending_forced_skills"] = st.session_state.get("ai_market_forced_skill_names", [])
            st.session_state["clear_ai_market_prompt"] = True

    if st.session_state.pop("clear_ai_market_prompt", False):
        st.session_state["ai_market_prompt"] = ""

    with st.container(border=True):
        st.markdown('<div class="command-bar-title">AI 行情问答</div>', unsafe_allow_html=True)
        with st.form("ai_market_prompt_form", clear_on_submit=True, border=False):
            ai_cols = st.columns([0.76, 0.24], vertical_alignment="top")
            with ai_cols[0]:
                inner_cols = st.columns(1)
                with inner_cols[0]:
                    _command_label("询问内容 / 提示词")
                    ai_prompt = st.text_input(
                        "询问 AI洞察",
                        placeholder="询问大盘主线、板块催化、个股消息面...",
                        label_visibility="collapsed",
                        key="ai_market_prompt",
                        autocomplete="off",
                    )
            with ai_cols[1]:
                st.markdown('<div class="command-field-label spacer">&nbsp;</div>', unsafe_allow_html=True)
                ai_submitted = st.form_submit_button("来财来财", use_container_width=True)
        if ai_submitted and ai_prompt.strip():
            st.session_state["pending_prompt"] = ai_prompt.strip()
            st.session_state["pending_keywords"] = DEFAULT_MARKET_KEYWORDS
            st.session_state["pending_forced_skills"] = st.session_state.get("ai_market_forced_skill_names", [])
            st.session_state["clear_ai_market_prompt"] = True
            st.rerun()
        if "ai_market_forced_skill_names" not in st.session_state:
            st.session_state["ai_market_forced_skill_names"] = []

        def _toggle_ai_skill(s_name):
            skills = set(st.session_state.get("ai_market_forced_skill_names", []))
            if s_name in skills:
                skills.remove(s_name)
            else:
                skills.add(s_name)
            st.session_state["ai_market_forced_skill_names"] = [name for name, _ in AI_SKILL_BUTTONS if name in skills]

        with st.expander("请选择Skill", expanded=False):
            st.markdown('<div class="ai-skill-buttons-container" style="display:none"></div>', unsafe_allow_html=True)
            selected_skills = set(st.session_state.get("ai_market_forced_skill_names", []))

            for skill_name, help_text in AI_SKILL_BUTTONS:
                display_name = "QQQ" if skill_name == "qqqq" else skill_name.replace("alphaear-", "").title()
                st.button(
                    display_name,
                    key=f"ai_skill_{skill_name.replace('-', '_')}",
                    help=help_text,
                    type="primary" if skill_name in selected_skills else "secondary",
                    use_container_width=False,
                    on_click=_toggle_ai_skill,
                    args=(skill_name,)
                )
        ai_forced_skills = st.session_state.get("ai_market_forced_skill_names", [])
elif page in {"个股行情", "市场情绪"}:
    with st.container(border=True):
        st.markdown('<div class="command-bar-title">参数与操作</div>', unsafe_allow_html=True)
        if page == "个股行情":
            command_cols = st.columns([0.76, 0.24], vertical_alignment="top")
            with command_cols[0]:
                inner_cols = st.columns(2)
                with inner_cols[0]:
                    _command_label("股票代码 / 名称")
                    stock_query = st.text_input(
                        "股票代码 / 名称",
                        placeholder="输入 600519、贵州茅台、茅台等",
                        help="支持 6 位股票代码、完整中文名和中文名称模糊匹配。",
                        key="stock_query",
                        autocomplete="off",
                        label_visibility="collapsed",
                    )
            with command_cols[1]:
                st.markdown('<div class="command-field-label spacer">&nbsp;</div>', unsafe_allow_html=True)
                run = st.button("来财来财", type="primary", use_container_width=True, key="run_stock_quote")

            matches = resolve_stock_query(stock_query, _stock_directory()) if stock_query.strip() else []
            if matches:
                selected = matches[0]
                code = str(selected.get("code") or "")
                name = str(selected.get("name") or "")
                st.caption(f"已匹配：{name}（{code}）")
            elif stock_query.strip():
                st.warning("没有匹配到股票。可以尝试输入 6 位代码、完整名称或更短的名称关键词。")

            with st.expander("DCF 估值假设", expanded=False):
                dcf_cols = st.columns(5, vertical_alignment="top")
                with dcf_cols[0]:
                    dcf_years = st.number_input("DCF 年数", min_value=1, max_value=10, value=5, step=1)
                with dcf_cols[1]:
                    dcf_growth = st.slider("现金流增长率", min_value=-20.0, max_value=30.0, value=5.0, step=0.5, format="%.2f%%")
                with dcf_cols[2]:
                    dcf_terminal_growth = st.slider("永续增长率", min_value=-5.0, max_value=6.0, value=2.0, step=0.25, format="%.2f%%")
                with dcf_cols[3]:
                    dcf_discount = st.slider("折现率", min_value=4.0, max_value=20.0, value=10.0, step=0.5, format="%.2f%%")
                with dcf_cols[4]:
                    dcf_margin = st.slider("安全边际", min_value=0.0, max_value=50.0, value=20.0, step=1.0, format="%.2f%%")
        elif page == "市场情绪":
            command_cols = st.columns([0.76, 0.24], vertical_alignment="top")
            with command_cols[0]:
                inner_cols = st.columns(2)
                with inner_cols[0]:
                    _command_label("交易日")
                    sentiment_date = st.date_input("交易日", value=sentiment_date, key="sentiment_date", label_visibility="collapsed")
                with inner_cols[1]:
                    _command_label("观察窗口")
                    sentiment_window = st.segmented_control(
                        "观察窗口",
                        options=[14, 30, 60],
                        default=60,
                        format_func=lambda x: f"{x}日",
                        key="sentiment_window_segment",
                        label_visibility="collapsed"
                    )
                    st.markdown(f'<div id="jocket-sentiment-window" data-window="{sentiment_window}日"></div>', unsafe_allow_html=True)
            with command_cols[1]:
                st.markdown('<div class="command-field-label spacer">&nbsp;</div>', unsafe_allow_html=True)
                run = st.button("来财来财", type="primary", use_container_width=True, key="run_market_sentiment")

            sentiment_refresh = False
            sentiment_backfill = False

dcf_assumptions = {
    "years": int(dcf_years),
    "cashflow_growth": float(dcf_growth) / 100,
    "terminal_growth": float(dcf_terminal_growth) / 100,
    "discount_rate": float(dcf_discount) / 100,
    "margin_of_safety": float(dcf_margin) / 100,
}

analysis_result = None
sentiment_result = None
run_error = None
ai_stock_summary = None
fundamental_context_result = None
stock_result_cache_key = "stock_analysis_result_cache"
market_result_cache_key = "market_sentiment_result_cache"
stock_job_state_key = "stock_analysis_background_job"
market_job_state_key = "market_sentiment_background_job"
stock_job_running = False
market_job_running = False

if "ai_market_messages" not in st.session_state:
    st.session_state["ai_market_messages"] = []

stock_job = st.session_state.get(stock_job_state_key) or {}
stock_future = stock_job.get("future")
if stock_future is not None:
    if stock_future.done():
        try:
            stock_payload = stock_future.result()
            st.session_state[stock_result_cache_key] = stock_payload
            if stock_payload.get("analysis_result"):
                latest_date = _latest_date(stock_payload["analysis_result"][1])
                summary_key = _stock_ai_summary_key(stock_payload.get("code", ""), latest_date, stock_payload["analysis_result"][0])
                st.session_state[summary_key] = stock_payload.get("ai_stock_summary")
            if page == "个股行情":
                if not code or _stock_job_signature(code, dcf_assumptions) == stock_job.get("signature"):
                    code = code or str(stock_payload.get("code") or "")
                    name = name or str(stock_payload.get("name") or "")
                    analysis_result = stock_payload.get("analysis_result")
                    fundamental_context_result = stock_payload.get("fundamental_context_result")
                    ai_stock_summary = stock_payload.get("ai_stock_summary")
        except Exception as exc:
            if page == "个股行情":
                run_error = f"{type(exc).__name__}: {exc}"
        finally:
            st.session_state.pop(stock_job_state_key, None)
    else:
        stock_job_running = page == "个股行情"

market_job = st.session_state.get(market_job_state_key) or {}
market_future = market_job.get("future")
if market_future is not None:
    if market_future.done():
        try:
            market_payload = market_future.result()
            st.session_state[market_result_cache_key] = market_payload
            st.session_state["market_sentiment_result"] = market_payload.get("sentiment_result")
            st.session_state["market_sentiment_window_days"] = int(market_payload.get("window_days") or 60)
            if page == "市场情绪" and _market_job_signature(sentiment_date, int(sentiment_window or 60)) == market_job.get("signature"):
                sentiment_result = market_payload.get("sentiment_result")
                sentiment_window = int(market_payload.get("window_days") or sentiment_window or 60)
        except Exception as exc:
            if page == "市场情绪":
                run_error = str(exc)
        finally:
            st.session_state.pop(market_job_state_key, None)
    else:
        market_job_running = page == "市场情绪"

if run and page == "个股行情":
    if not code:
        run_error = "请先输入股票代码或股票名称，并从匹配结果中选择一个个股。"
    else:
        signature = _stock_job_signature(code, dcf_assumptions)
        progress = {"stage": "fetch"}
        st.session_state[stock_job_state_key] = {
            "signature": signature,
            "code": code,
            "name": name,
            "progress": progress,
            "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "future": _analysis_executor().submit(_run_stock_analysis_job, code, name, copy.deepcopy(dcf_assumptions), progress),
        }
        stock_job_running = True
elif run and page == "市场情绪":
    signature = _market_job_signature(sentiment_date, int(sentiment_window or 60))
    progress = {"stage": "fetch"}
    st.session_state[market_job_state_key] = {
        "signature": signature,
        "trade_date": pd.to_datetime(sentiment_date).date(),
        "window_days": int(sentiment_window or 60),
        "progress": progress,
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "future": _analysis_executor().submit(_run_market_sentiment_job, sentiment_date, int(sentiment_window or 60), progress),
    }
    market_job_running = True

if page == "个股行情" and analysis_result is None and not run_error and not stock_job_running:
    cached_stock_result = st.session_state.get(stock_result_cache_key) or {}
    cached_code = str(cached_stock_result.get("code") or "")
    cached_dcf = cached_stock_result.get("dcf_assumptions") or {}
    if cached_stock_result.get("analysis_result") and (not code or cached_code == code) and cached_dcf == dcf_assumptions:
        code = code or cached_code
        name = name or str(cached_stock_result.get("name") or "")
        analysis_result = cached_stock_result.get("analysis_result")
        fundamental_context_result = cached_stock_result.get("fundamental_context_result")
        ai_stock_summary = cached_stock_result.get("ai_stock_summary")

if page == "市场情绪" and sentiment_result is None and not run_error and not market_job_running:
    cached_market_result = st.session_state.get(market_result_cache_key) or {}
    cached_market_date = cached_market_result.get("trade_date")
    cached_market_window = int(cached_market_result.get("window_days") or 0)
    current_market_date = pd.to_datetime(sentiment_date).date()
    current_market_window = int(sentiment_window or 60)
    if (
        cached_market_result.get("sentiment_result")
        and cached_market_date == current_market_date
        and cached_market_window == current_market_window
    ):
        sentiment_result = cached_market_result.get("sentiment_result")
        sentiment_window = cached_market_window
    elif "market_sentiment_result" in st.session_state and not cached_market_result:
        sentiment_result = st.session_state.get("market_sentiment_result")
        sentiment_window = int(st.session_state.get("market_sentiment_window_days", sentiment_window or 60))


# Mode Info for Hero
_mode_info = {
    "AI洞察": ("AI洞察", "询问大盘主线、板块催化或个股消息面，获取结合最新信号的深度研判。"),
    "个股行情": ("个股行情", "输入股票代码或名称后运行，系统会自动生成趋势评级、量价证据、基本面与消息面研究视图。"),
    "市场情绪": ("市场情绪", "复盘全市场涨停生态、情绪周期、板块梯队和次日条件观察池。"),
}

# Default Hero Values
hero_code = (
    "自然语言"
    if page == "AI洞察"
    else ("全市场" if page == "市场情绪" else (f"{name} {code}".strip() if code else "未选择个股"))
)
hero_source = INTERNAL_DATA_LABEL
hero_latest = "-"
hero_title, hero_subtitle = _mode_info.get(page, ("A股智能雷达", "..."))

if analysis_result:
    score_for_hero, hist_for_hero, _ = analysis_result
    hero_latest = _latest_date(hist_for_hero)
    profile = ((fundamental_context_result or {}).get("payload", {}) or {}).get("profile", {}) or {}
    profile_name = profile.get("name")
    stock_name = _chinese_name_for_code(profile.get("code") or code, name or profile_name or code or "个股行情")
    stock_code = profile.get("code") or score_for_hero.get("code") or code
    exchange = profile.get("exchange")
    industry = profile.get("industry_cn") or profile.get("industry")
    hero_code = str(stock_code or code or "-")
    hero_title = f"{stock_name}（{hero_code}）"
    parts = [part for part in [exchange, industry] if part and str(part) not in {"暂未获取", "当前数据源暂不支持"}]
    latest = score_for_hero.get("latest", {}) or {}
    hero_subtitle = (
        f"{'；'.join(parts) + '；' if parts else ''}"
        f"最新交易日 {hero_latest}，短线评分 {format_price(score_for_hero.get('short_score'), 1)} / 100，"
        f"当日涨跌 {format_percent(latest.get('ret_1d'))}。"
    )
    business_summary = _compact_business_summary(str(profile.get("business") or ""))
    if business_summary:
        hero_subtitle = f"{hero_subtitle}。{business_summary}"
elif sentiment_result:
    hero_latest = sentiment_result.get("trade_date", "-")
    metrics_for_hero = sentiment_result.get("metrics", {})
    hero_title = "市场情绪"
    hero_subtitle = (
        f"{metrics_for_hero.get('period', '周期待确认')}：情绪综合指数 {format_price(metrics_for_hero.get('emotion_score'), 1)}，"
        f"涨停/炸板/跌停 {metrics_for_hero.get('limit_up_count', '-')} / {metrics_for_hero.get('broken_count', '-')} / {metrics_for_hero.get('limit_down_count', '-')}。"
    )

# Render Global Hero (Page-Aware)
if page in {"个股行情", "市场情绪"}:
    ai_summary_to_pass = ai_stock_summary if page == "个股行情" else None
    render_hero(
        hero_code,
        hero_source,
        hero_latest,
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        title=hero_title,
        subtitle=hero_subtitle,
        ai_summary=ai_summary_to_pass,
    )

# Dashboard Content
if page == "AI洞察":
    _render_ai_market_dashboard(config)
elif stock_job_running:
    _render_background_job_fragment(
        stock_job_state_key,
        "个股查询进行中",
        "正在拉取行情、基本面、资金和消息面信号。可以先切到其他功能页；任务完成后会自动接上结果。",
    )
elif market_job_running:
    _render_background_job_fragment(
        market_job_state_key,
        "市场情绪分析进行中",
        "正在拉取涨停生态、板块梯队、资金验证和观察池信号。可以先切到其他功能页；任务完成后会自动接上结果。",
    )
elif run_error:
    with st.container(border=True):
        st.markdown('<div class="chart-title"><span>运行失败</span><span class="pill pill-orange">需要处理</span></div>', unsafe_allow_html=True)
        st.error(f"本次请求没有成功生成结果。请稍后重试，或更换个股验证最新行情源。\n\n**错误详情：** `{run_error}`")
        with st.expander("调试信息（Streamlit Cloud / Railway 排错用）"):
            st.code(run_error)
elif analysis_result:
    score, hist, report_path = analysis_result
    _render_analysis_dashboard(score, hist, report_path, dcf_assumptions, fundamental_context_result)
elif sentiment_result:
    _render_market_sentiment_dashboard(sentiment_result, int(sentiment_window or 60))
elif page == "投研分析":
    render_tradingagents_dashboard()
else:
    # Empty state handled by dynamic hero above
    pass
