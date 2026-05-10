from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components


PLOT_BG = "rgba(0,0,0,0)"
PAPER_BG = "rgba(0,0,0,0)"
GRID = "rgba(255,255,255,0.08)"
TEXT = "#F5F7FA"
MUTED = "#A7ADBA"
GREEN = "#33D69F"
RED = "#FF5C7A"
BLUE = "#5B8CFF"
CYAN = "#37E8FF"
PURPLE = "#9B5CFF"
ORANGE = "#FFB86B"


def load_css(path: str = "assets/styles.css") -> None:
    css_path = Path(path)
    if css_path.exists():
        st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)
        components.html(
            """
            <script>
            (() => {
              const doc = window.parent.document;
              const selector = ".hero-meta-item,.metric-card,.insight-card,.rank-card,.chart-card,.section-card,.profile-card";
              let active = null;
              doc.addEventListener("pointermove", (event) => {
                const card = doc.elementFromPoint(event.clientX, event.clientY)?.closest(selector);
                if (active && active !== card) active.removeAttribute("data-cursor-glow");
                active = card;
                if (!card) return;
                const rect = card.getBoundingClientRect();
                card.style.setProperty("--cursor-x", `${event.clientX - rect.left}px`);
                card.style.setProperty("--cursor-y", `${event.clientY - rect.top}px`);
                card.setAttribute("data-cursor-glow", "true");
              }, { passive: true });
              doc.addEventListener("pointerleave", () => {
                if (active) active.removeAttribute("data-cursor-glow");
                active = null;
              }, { passive: true });
            })();
            </script>
            """,
            height=0,
        )


def _safe(value, default="-"):
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    return value


def format_number_cn(value, digits: int = 2, suffix: str = "") -> str:
    value = _safe(value, None)
    if value is None:
        return "-"
    try:
        num = float(value)
    except Exception:
        return str(value)
    sign = "-" if num < 0 else ""
    num = abs(num)
    if num >= 100_000_000:
        return f"{sign}{num / 100_000_000:.{digits}f}亿{suffix}"
    if num >= 10_000:
        return f"{sign}{num / 10_000:.{digits}f}万{suffix}"
    return f"{sign}{num:,.{digits}f}{suffix}"


def format_percent(value, digits: int = 2) -> str:
    value = _safe(value, None)
    if value is None:
        return "-"
    try:
        num = float(value)
    except Exception:
        return str(value)
    if abs(num) <= 1:
        num *= 100
    return f"{num:+.{digits}f}%"


def format_price(value, digits: int = 2) -> str:
    value = _safe(value, None)
    if value is None:
        return "-"
    try:
        return f"{float(value):,.{digits}f}"
    except Exception:
        return str(value)


def render_hero(
    code: str = "-",
    data_source: str = "-",
    latest_date: str = "-",
    updated_at: str | None = None,
) -> None:
    updated_at = updated_at or datetime.now().strftime("%Y-%m-%d %H:%M")
    html = f"""
    <section class="hero-shell">
      <div class="hero-content">
        <div>
          <div class="eyebrow">A-share intelligence dashboard</div>
          <h1 class="hero-title">AI Stock Radar</h1>
          <p class="hero-subtitle">A-share opportunity scanner with multi-source market data, technical signals and explainable scoring.</p>
        </div>
        <div class="hero-meta-grid">
          <div class="hero-meta-item"><div class="meta-label">Ticker</div><div class="meta-value">{escape(str(code or "-"))}</div></div>
          <div class="hero-meta-item"><div class="meta-label">Data Source</div><div class="meta-value">{escape(str(data_source or "-"))}</div></div>
          <div class="hero-meta-item"><div class="meta-label">Latest Session</div><div class="meta-value">{escape(str(latest_date or "-"))}</div></div>
          <div class="hero-meta-item"><div class="meta-label">Updated</div><div class="meta-value">{escape(str(updated_at))}</div></div>
        </div>
      </div>
    </section>
    """
    st.markdown(html, unsafe_allow_html=True)


def metric_card(label: str, value: str, footnote: str = "", tone: str = "cyan", indicator: str = "neutral") -> str:
    tone_color = {
        "green": "rgba(51, 214, 159, 0.24)",
        "red": "rgba(255, 92, 122, 0.24)",
        "cyan": "rgba(55, 232, 255, 0.22)",
        "purple": "rgba(155, 92, 255, 0.22)",
        "orange": "rgba(255, 184, 107, 0.20)",
        "blue": "rgba(91, 140, 255, 0.22)",
    }.get(tone, "rgba(91, 140, 255, 0.22)")
    pill_class = {
        "green": "pill-green",
        "red": "pill-red",
        "cyan": "pill-cyan",
        "purple": "pill-purple",
        "orange": "pill-orange",
        "blue": "pill-cyan",
    }.get(tone, "pill-cyan")
    icon = {"up": "UP", "down": "DOWN", "neutral": "LIVE"}.get(indicator, "LIVE")
    return (
        f'<div class="metric-card" style="--card-glow:{tone_color}">'
        f'<div class="metric-inner">'
        f'<div class="metric-label">{escape(label)}</div>'
        f'<div class="metric-value">{escape(value)}</div>'
        f'<div class="metric-foot"><span>{escape(footnote)}</span><span class="pill {pill_class}">{icon}</span></div>'
        f'</div></div>'
    )


def render_bento_grid(cards: Iterable[str]) -> None:
    st.markdown('<div class="bento-grid">' + "".join(cards) + "</div>", unsafe_allow_html=True)


def bento_card_start(title: str = "", badge: str = "") -> None:
    badge_html = f'<span class="pill pill-cyan">{escape(badge)}</span>' if badge else ""
    st.markdown(
        f'<div class="section-card"><div class="chart-title"><span>{escape(title)}</span>{badge_html}</div>',
        unsafe_allow_html=True,
    )


def bento_card_end() -> None:
    st.markdown("</div>", unsafe_allow_html=True)


def render_score_badge(score) -> str:
    try:
        num = float(score)
    except Exception:
        num = 0
    if num >= 75:
        cls = "pill-green"
        label = "Strong"
    elif num >= 60:
        cls = "pill-cyan"
        label = "Watch"
    else:
        cls = "pill-orange"
        label = "Cautious"
    return f'<span class="pill {cls}">{label} {num:.1f}</span>'


def render_warning_badge(text: str) -> str:
    return f'<span class="risk-badge" data-tip="{escape(text)}">{escape(text[:18])}{"..." if len(text) > 18 else ""}</span>'


def render_section_title(title: str, subtitle: str = "") -> None:
    st.markdown(f'<h2 class="section-title">{escape(title)}</h2>', unsafe_allow_html=True)
    if subtitle:
        st.markdown(f'<p class="section-subtitle">{escape(subtitle)}</p>', unsafe_allow_html=True)


def render_insight_cards(insights: list[dict]) -> None:
    cards = []
    for item in insights:
        tone = item.get("tone", "cyan")
        pill_class = {
            "green": "pill-green",
            "red": "pill-red",
            "orange": "pill-orange",
            "purple": "pill-purple",
            "cyan": "pill-cyan",
        }.get(tone, "pill-cyan")
        cards.append(
            f'<div class="insight-card">'
            f'<div class="insight-label">{escape(item.get("label", "Insight"))}</div>'
            f'<div class="insight-title">{escape(item.get("title", "-"))}</div>'
            f'<div class="insight-body">{escape(item.get("body", "-"))}</div>'
            f'<div style="margin-top:14px"><span class="pill {pill_class}">{escape(item.get("badge", "Signal"))}</span></div>'
            f'</div>'
        )
    st.markdown('<div class="insight-grid">' + "".join(cards) + "</div>", unsafe_allow_html=True)


def _base_fig(fig: go.Figure, height: int = 420) -> go.Figure:
    fig.update_layout(
        height=height,
        paper_bgcolor=PAPER_BG,
        plot_bgcolor=PLOT_BG,
        font=dict(color=TEXT, family="Inter, system-ui, sans-serif"),
        margin=dict(l=12, r=12, t=28, b=12),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(color=MUTED)),
    )
    fig.update_xaxes(showgrid=False, color=MUTED, rangeslider_visible=False)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID, color=MUTED)
    return fig


def plot_price_trend(df: pd.DataFrame) -> go.Figure:
    data = df.tail(180).copy()
    fig = go.Figure()
    has_ohlc = all(col in data.columns for col in ["open", "high", "low", "close"])
    if has_ohlc:
        fig.add_trace(
            go.Candlestick(
                x=data["date"],
                open=data["open"],
                high=data["high"],
                low=data["low"],
                close=data["close"],
                name="K line",
                increasing_line_color=GREEN,
                decreasing_line_color=RED,
                increasing_fillcolor="rgba(51,214,159,0.35)",
                decreasing_fillcolor="rgba(255,92,122,0.32)",
            )
        )
    else:
        fig.add_trace(go.Scatter(x=data["date"], y=data["close"], name="Close", mode="lines", line=dict(color=CYAN, width=2.4)))
    for ma, color in [("ma20", CYAN), ("ma60", BLUE), ("ma120", PURPLE)]:
        if ma in data.columns and data[ma].notna().any():
            fig.add_trace(go.Scatter(x=data["date"], y=data[ma], name=ma.upper(), mode="lines", line=dict(color=color, width=1.8)))
    return _base_fig(fig, 460)


def plot_volume(df: pd.DataFrame) -> go.Figure:
    data = df.tail(120).copy()
    prev_close = data["close"].shift(1)
    colors = np.where(data["close"] >= prev_close, GREEN, RED)
    fig = go.Figure(
        go.Bar(
            x=data["date"],
            y=data.get("volume", pd.Series(index=data.index, data=0)),
            marker_color=colors,
            name="Volume",
            hovertemplate="%{x}<br>Volume %{y:,.0f}<extra></extra>",
        )
    )
    return _base_fig(fig, 330)


def plot_price_volume_scatter(df: pd.DataFrame) -> go.Figure:
    data = df.tail(120).copy()
    amount = data.get("amount_est")
    if amount is None:
        amount = data["close"] * data.get("volume", 0)
    size = np.clip((amount.fillna(0) / max(float(amount.fillna(0).max() or 1), 1)) * 34 + 8, 8, 42)
    colors = np.where(data.get("ret_1d", data["close"].pct_change()).fillna(0) >= 0, GREEN, RED)
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=data["close"],
            y=amount,
            mode="markers",
            marker=dict(size=size, color=colors, opacity=0.72, line=dict(color="rgba(255,255,255,0.24)", width=1)),
            text=data["date"].dt.strftime("%Y-%m-%d") if pd.api.types.is_datetime64_any_dtype(data["date"]) else data["date"].astype(str),
            name="Sessions",
            hovertemplate="%{text}<br>Close %{x:.2f}<br>Amount %{y:,.0f}<extra></extra>",
        )
    )
    if len(data):
        latest = data.iloc[-1]
        latest_amount = float((latest.get("amount_est") if "amount_est" in data.columns else latest["close"] * latest.get("volume", 0)) or 0)
        fig.add_trace(
            go.Scatter(
                x=[latest["close"]],
                y=[latest_amount],
                mode="markers",
                marker=dict(size=22, color=CYAN, line=dict(color=TEXT, width=2)),
                name="Latest",
                hovertemplate="Latest<br>Close %{x:.2f}<br>Amount %{y:,.0f}<extra></extra>",
            )
        )
    fig.update_xaxes(title="Close")
    fig.update_yaxes(title="Amount")
    return _base_fig(fig, 360)


def plot_rsi(df: pd.DataFrame) -> go.Figure:
    data = df.tail(160).copy()
    fig = go.Figure()
    if "rsi14" in data.columns:
        fig.add_trace(go.Scatter(x=data["date"], y=data["rsi14"], name="RSI 14", line=dict(color=ORANGE, width=2.4)))
    fig.add_hrect(y0=70, y1=100, fillcolor="rgba(255,92,122,0.10)", line_width=0)
    fig.add_hrect(y0=0, y1=30, fillcolor="rgba(51,214,159,0.10)", line_width=0)
    fig.add_hline(y=70, line_dash="dot", line_color="rgba(255,92,122,0.55)")
    fig.add_hline(y=30, line_dash="dot", line_color="rgba(51,214,159,0.55)")
    fig.update_yaxes(range=[0, 100])
    return _base_fig(fig, 330)


def plot_macd(df: pd.DataFrame) -> go.Figure:
    data = df.tail(160).copy()
    fig = go.Figure()
    if "macd_hist" in data.columns:
        colors = np.where(data["macd_hist"].fillna(0) >= 0, GREEN, RED)
        fig.add_trace(go.Bar(x=data["date"], y=data["macd_hist"], marker_color=colors, name="Histogram"))
    if "macd_diff" in data.columns:
        fig.add_trace(go.Scatter(x=data["date"], y=data["macd_diff"], name="DIF", line=dict(color=CYAN, width=2)))
    if "macd_dea" in data.columns:
        fig.add_trace(go.Scatter(x=data["date"], y=data["macd_dea"], name="DEA", line=dict(color=PURPLE, width=2)))
    return _base_fig(fig, 330)


def plot_kdj(df: pd.DataFrame) -> go.Figure:
    data = df.tail(160).copy()
    fig = go.Figure()
    for col, name, color in [("kdj_k", "K", CYAN), ("kdj_d", "D", PURPLE), ("kdj_j", "J", ORANGE)]:
        if col in data.columns:
            fig.add_trace(go.Scatter(x=data["date"], y=data[col], name=name, line=dict(color=color, width=2)))
    return _base_fig(fig, 330)


def plot_score_breakdown(score_detail: dict, title: str = "Score Breakdown") -> go.Figure:
    labels = list(score_detail.keys()) or ["Score"]
    values = [float(score_detail.get(label, 0) or 0) for label in labels]
    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker=dict(
                color=values,
                colorscale=[[0, RED], [0.5, BLUE], [1, GREEN]],
                line=dict(color="rgba(255,255,255,0.22)", width=1),
            ),
            hovertemplate="%{y}<br>Score %{x:.1f}<extra></extra>",
        )
    )
    fig.update_layout(title=dict(text=title, font=dict(size=15, color=TEXT)), yaxis=dict(autorange="reversed"))
    return _base_fig(fig, 330)


def _breakdown_frame(breakdown: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "dimension": item.get("dimension"),
            "score": float(item.get("score", 0) or 0),
            "max_score": float(item.get("max_score", 0) or 0),
            "score_rate": float(item.get("score_rate", 0) or 0),
        }
        for item in breakdown
    ])


def plot_explainable_bar(breakdown: list[dict], title: str = "评分维度") -> go.Figure:
    data = _breakdown_frame(breakdown)
    if data.empty:
        return _base_fig(go.Figure(), 340)
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=data["max_score"],
            y=data["dimension"],
            orientation="h",
            marker=dict(color="rgba(255,255,255,0.09)", line=dict(color="rgba(255,255,255,0.12)", width=1)),
            name="满分",
            hovertemplate="%{y}<br>满分 %{x:.1f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            x=data["score"],
            y=data["dimension"],
            orientation="h",
            marker=dict(color=data["score_rate"], colorscale=[[0, RED], [0.55, BLUE], [1, GREEN]], line=dict(color="rgba(255,255,255,0.20)", width=1)),
            name="当前得分",
            hovertemplate="%{y}<br>得分 %{x:.1f}<extra></extra>",
        )
    )
    fig.update_layout(title=dict(text=title, font=dict(size=15, color=TEXT)), barmode="overlay", yaxis=dict(autorange="reversed"))
    return _base_fig(fig, 350)


def plot_score_radar(breakdown: list[dict], title: str = "得分率雷达") -> go.Figure:
    data = _breakdown_frame(breakdown)
    if data.empty:
        return _base_fig(go.Figure(), 340)
    labels = data["dimension"].tolist()
    values = (data["score_rate"] * 100).round(1).tolist()
    labels.append(labels[0])
    values.append(values[0])
    fig = go.Figure(
        go.Scatterpolar(
            r=values,
            theta=labels,
            fill="toself",
            name="得分率",
            line=dict(color=CYAN, width=2.4),
            fillcolor="rgba(55,232,255,0.16)",
            hovertemplate="%{theta}<br>得分率 %{r:.1f}%<extra></extra>",
        )
    )
    fig.update_layout(
        title=dict(text=title, font=dict(size=15, color=TEXT)),
        polar=dict(
            bgcolor="rgba(0,0,0,0)",
            radialaxis=dict(range=[0, 100], gridcolor=GRID, color=MUTED),
            angularaxis=dict(gridcolor=GRID, color=MUTED),
        ),
        showlegend=False,
    )
    return _base_fig(fig, 360)


def plot_score_waterfall(breakdown: list[dict], title: str = "贡献度瀑布图") -> go.Figure:
    data = _breakdown_frame(breakdown)
    if data.empty:
        return _base_fig(go.Figure(), 340)
    fig = go.Figure(
        go.Waterfall(
            name="贡献",
            orientation="v",
            measure=["relative"] * len(data) + ["total"],
            x=data["dimension"].tolist() + ["总分"],
            y=data["score"].tolist() + [0],
            connector={"line": {"color": "rgba(255,255,255,0.25)"}},
            increasing={"marker": {"color": GREEN}},
            totals={"marker": {"color": CYAN}},
            hovertemplate="%{x}<br>%{y:.1f}<extra></extra>",
        )
    )
    fig.update_layout(title=dict(text=title, font=dict(size=15, color=TEXT)))
    return _base_fig(fig, 360)


def plot_risk_deductions(breakdown: list[dict], title: str = "风险扣分 / 缺口") -> go.Figure:
    rows = []
    for item in breakdown:
        gap = float(item.get("max_score", 0) or 0) - float(item.get("score", 0) or 0)
        if gap > 0:
            rows.append({"dimension": item.get("dimension"), "gap": gap})
    data = pd.DataFrame(rows)
    if data.empty:
        data = pd.DataFrame([{"dimension": "暂无明显扣分", "gap": 0}])
    fig = go.Figure(
        go.Bar(
            x=data["gap"],
            y=data["dimension"],
            orientation="h",
            marker=dict(color=ORANGE, line=dict(color="rgba(255,255,255,0.20)", width=1)),
            hovertemplate="%{y}<br>扣分/缺口 %{x:.1f}<extra></extra>",
        )
    )
    fig.update_layout(title=dict(text=title, font=dict(size=15, color=TEXT)), yaxis=dict(autorange="reversed"))
    return _base_fig(fig, 330)


def format_evidence_value(key: str, value) -> str:
    if value is None or value == "":
        return "暂未接入"
    if isinstance(value, str):
        return value
    if key in {"return_1d", "return_5d", "return_20d", "return_60d", "return_120d", "distance_to_20d_high", "distance_to_ma20", "volatility_60d", "max_drawdown_60d", "amplitude", "roe", "roa", "dividend_yield", "dcf_discount_pct", "top_board_pct", "avg_top3_board_pct"}:
        return format_percent(value)
    if key in {"volume", "volume_ma5", "volume_ma20", "amount_est", "amount_avg_20d"}:
        return format_number_cn(value)
    if key in {"history_days"}:
        return f"{int(value)}"
    return format_price(value, 2)


def render_evidence_table(evidence: dict) -> None:
    labels = {
        "close": "最新收盘价",
        "open": "开盘价",
        "high": "最高价",
        "low": "最低价",
        "ma5": "MA5",
        "ma10": "MA10",
        "ma20": "MA20",
        "ma60": "MA60",
        "ma120": "MA120",
        "ma250": "MA250",
        "return_1d": "当日涨跌幅",
        "return_5d": "近5日涨跌幅",
        "return_20d": "近20日涨跌幅",
        "return_60d": "近60日涨跌幅",
        "return_120d": "近120日涨跌幅",
        "volume": "成交量",
        "volume_ma5": "5日均量",
        "volume_ma20": "20日均量",
        "volume_ratio_5": "5日量比",
        "volume_ratio_20": "20日量比",
        "amount_est": "估算成交额",
        "amount_avg_20d": "20日平均成交额",
        "turnover_rate": "换手率",
        "rsi14": "RSI14",
        "macd_diff": "MACD DIF",
        "macd_dea": "MACD DEA",
        "macd_hist": "MACD Histogram",
        "kdj_k": "KDJ K",
        "kdj_d": "KDJ D",
        "kdj_j": "KDJ J",
        "high_20d": "近20日最高价",
        "distance_to_20d_high": "距20日高点",
        "distance_to_ma20": "距MA20偏离",
        "volatility_60d": "60日波动率",
        "max_drawdown_60d": "60日最大回撤",
        "data_source": "数据源",
        "history_days": "历史样本天数",
        "industry": "行业",
        "industry_cn": "中文行业/主板块",
        "sector": "Sector",
        "belong_boards": "所属板块/概念",
        "top_board": "最强所属板块",
        "top_board_pct": "最强板块涨幅",
        "avg_top3_board_pct": "前三板块均涨幅",
        "positive_board_count": "上涨板块数",
        "board_net_flow_sum": "匹配板块资金净额",
        "board_source": "板块数据源",
    }
    rows = [
        {"指标": label, "数值": format_evidence_value(key, evidence.get(key))}
        for key, label in labels.items()
        if key in evidence
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True, height=420)


def render_dimension_cards(breakdown: list[dict], namespace: str = "score") -> None:
    for idx, item in enumerate(breakdown):
        title = f"{item.get('dimension', '-')}: {format_price(item.get('score'), 1)} / {format_price(item.get('max_score'), 0)}"
        with st.expander(title, expanded=idx == 0):
            st.markdown(f"**评分逻辑：** {item.get('logic', '-')}")
            st.markdown(f"**权重：** {float(item.get('weight', 0) or 0):.0%}　**得分率：** {float(item.get('score_rate', 0) or 0):.1%}")
            st.markdown("**关键数据：**")
            data_points = item.get("data_points", {}) or {}
            rows = [{"数据项": key, "当前值": format_evidence_value(key, value)} for key, value in data_points.items()]
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True, height=min(260, 44 + 36 * max(1, len(rows))))
            col_pos, col_neg = st.columns(2)
            with col_pos:
                st.markdown("**加分项**")
                for factor in item.get("positive_factors", []):
                    st.markdown(f"- {factor}")
            with col_neg:
                st.markdown("**扣分项 / 限制**")
                for factor in item.get("negative_factors", []):
                    st.markdown(f"- {factor}")
            st.info(item.get("decision_impact", "-"))


def format_ratio(value, digits: int = 2) -> str:
    value = _safe(value, None)
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.{digits}f}x"
    except Exception:
        return str(value)


def format_na(value, formatter=None) -> str:
    value = _safe(value, None)
    if value is None or value == "":
        return "暂未获取"
    if formatter:
        return formatter(value)
    return str(value)


def render_company_profile(profile: dict, summary: str = "") -> None:
    left_badges = [
        ("市场", profile.get("market")),
        ("行业", profile.get("industry_cn") or profile.get("industry")),
        ("数据源", profile.get("data_source")),
    ]
    badges_html = "".join(
        f'<span class="pill pill-cyan">{escape(label)} · {escape(str(value or "暂未获取"))}</span>'
        for label, value in left_badges
    )
    kv = [
        ("交易所", profile.get("exchange")),
        ("上市时间", profile.get("list_date")),
        ("总市值", format_number_cn(profile.get("market_cap")) if profile.get("market_cap") else "暂未获取"),
        ("流通市值", format_number_cn(profile.get("float_market_cap")) if profile.get("float_market_cap") else "暂未获取"),
        ("总股本", format_number_cn(profile.get("shares_outstanding")) if profile.get("shares_outstanding") else "暂未获取"),
        ("流通股本", format_number_cn(profile.get("float_shares")) if profile.get("float_shares") else "暂未获取"),
        ("最新收盘价", format_price(profile.get("latest_price")) if profile.get("latest_price") else "暂未获取"),
        ("数据更新", profile.get("updated_at")),
        ("员工数", format_number_cn(profile.get("employees"), 0) if profile.get("employees") else "暂未获取"),
        ("Sector", profile.get("sector")),
    ]
    kv_html = "".join(
        f'<div class="profile-kv"><span>{escape(label)}</span><strong>{escape(str(value or "暂未获取"))}</strong></div>'
        for label, value in kv
    )
    business = profile.get("business") or "当前数据源暂不支持"
    if len(str(business)) > 360:
        business = str(business)[:360] + "..."
    html = f"""
    <div class="profile-card">
      <div class="profile-main">
        <div class="eyebrow">Company Identity</div>
        <h3>{escape(str(profile.get("name") or profile.get("code") or "-"))}</h3>
        <div class="profile-code">{escape(str(profile.get("code") or "-"))} · {escape(str(profile.get("yahoo_code") or "-"))}</div>
        <div class="profile-badges">{badges_html}</div>
        <p>{escape(summary or str(business))}</p>
      </div>
      <div class="profile-kv-grid">{kv_html}</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)
    with st.expander("主营业务简介", expanded=False):
        st.write(business)
    boards = profile.get("belong_boards") or []
    if boards:
        st.caption("所属板块 / 概念：" + "、".join(map(str, boards[:8])))


def render_valuation_metric_cards(metrics: dict) -> None:
    def money_or_na(value):
        return "N/A" if _safe(value, None) is None else format_number_cn(value)

    def percent_or_na(value):
        return "N/A" if _safe(value, None) is None else format_percent(value)

    def status(value, metric):
        if value is None:
            return "暂无数据", "orange"
        try:
            num = float(value)
        except Exception:
            return "中性", "cyan"
        if metric == "pe":
            if 10 <= num <= 25:
                return "有吸引力", "green"
            if num > 60 or num <= 0:
                return "风险偏高", "red"
            if num > 40:
                return "偏贵", "orange"
        if metric == "pb":
            if 1 <= num <= 3:
                return "有吸引力", "green"
            if num > 5:
                return "偏贵", "orange"
        if metric in {"roe", "roa"}:
            if num >= (0.15 if metric == "roe" else 0.07):
                return "有吸引力", "green"
            if num < 0.03:
                return "风险偏高", "orange"
        if metric == "de":
            if num < 1:
                return "有吸引力", "green"
            if num > 2:
                return "风险偏高", "orange"
        return "中性", "cyan"

    specs = [
        ("市值", money_or_na(metrics.get("market_cap")), "总市值", "market_cap", "cyan"),
        ("PE TTM", format_ratio(metrics.get("pe_ttm")), "市盈率，盈利为正时更有解释力", "pe", None),
        ("PB", format_ratio(metrics.get("pb")), "市净率，需结合 ROE", "pb", None),
        ("PS", format_ratio(metrics.get("ps")), "市销率，适合收入型比较", "ps", "blue"),
        ("股息率", percent_or_na(metrics.get("dividend_yield")), "现金分红收益率", "dy", "purple"),
        ("ROE", percent_or_na(metrics.get("roe")), "净利润 / 股东权益", "roe", None),
        ("ROA", percent_or_na(metrics.get("roa")), "净利润 / 总资产", "roa", None),
        ("D/E", format_ratio(metrics.get("debt_to_equity")), "总负债 / 股东权益代理", "de", None),
    ]
    cards = []
    for label, value, note, key, forced_tone in specs:
        raw_map = {"pe": "pe_ttm", "pb": "pb", "roe": "roe", "roa": "roa", "de": "debt_to_equity", "ps": "ps", "dy": "dividend_yield"}
        raw = metrics.get(raw_map.get(key, key))
        status_label, tone = status(raw, key)
        if forced_tone:
            tone = forced_tone
        cards.append(metric_card(label, value, f"{note} · {status_label}", tone, "neutral"))
    render_bento_grid(cards)


def plot_ratings_snapshot(ratings: dict) -> go.Figure:
    scores = ratings.get("scores", {}) if ratings else {}
    usable = {key: value for key, value in scores.items() if value is not None}
    if not usable:
        return _base_fig(go.Figure(), 390)
    labels = list(usable.keys())
    values = [float(v) for v in usable.values()]
    labels.append(labels[0])
    values.append(values[0])
    fig = go.Figure(
        go.Scatterpolar(
            r=values,
            theta=labels,
            fill="toself",
            name="Rating",
            line=dict(color=CYAN, width=2.6),
            fillcolor="rgba(55,232,255,0.18)",
            hovertemplate="%{theta}<br>评分 %{r:.1f} / 5<extra></extra>",
        )
    )
    fig.update_layout(
        polar=dict(
            bgcolor="rgba(0,0,0,0)",
            radialaxis=dict(range=[0, 5], tickvals=[1, 2, 3, 4, 5], gridcolor=GRID, color=MUTED),
            angularaxis=dict(gridcolor=GRID, color=MUTED),
        ),
        showlegend=False,
    )
    return _base_fig(fig, 390)


def render_ratings_list(ratings: dict) -> None:
    scores = ratings.get("scores", {}) if ratings else {}
    label_map = {
        "DCF": "DCF 简化估值",
        "ROE": "Return On Equity",
        "ROA": "Return On Assets",
        "D/E": "Debt To Equity",
        "P/E": "Price To Earnings",
        "P/B": "Price To Book",
        "Dividend Yield": "Dividend Yield",
        "Revenue Growth": "Revenue Growth",
        "Net Profit Growth": "Net Profit Growth",
    }
    rows = []
    for key, label in label_map.items():
        value = scores.get(key)
        value_text = "N/A" if value is None else f"{float(value):.1f}"
        rows.append(
            f'<div class="rating-row"><span>{escape(label)}</span><strong>{escape(value_text)}</strong></div>'
        )
    overall = ratings.get("overall")
    rating = ratings.get("rating", "数据受限")
    html = (
        '<div class="rating-list">'
        + "".join(rows)
        + f'<div class="rating-overall"><span>Overall Score</span><strong>{escape("N/A" if overall is None else f"{overall:.1f}")}</strong><em>{escape(str(rating))}</em></div>'
        + "</div>"
    )
    st.markdown(html, unsafe_allow_html=True)


def _financial_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    view = df.copy()
    rename = {
        "period": "报告期",
        "totalRevenue": "营业收入",
        "grossProfit": "毛利润",
        "netIncome": "净利润",
        "deductedNetIncome": "扣非净利润",
        "operatingCashFlow": "经营现金流",
        "freeCashFlow": "自由现金流",
        "totalAssets": "总资产",
        "totalLiab": "总负债",
        "totalStockholderEquity": "股东权益",
        "grossMargin": "毛利率",
        "netMargin": "净利率",
        "roe": "ROE",
        "roa": "ROA",
        "debtToEquity": "D/E",
        "eps": "EPS",
        "bvps": "BVPS",
        "dividend": "分红金额",
        "dividendYield": "股息率",
    }
    keep = [col for col in rename if col in view.columns]
    view = view[keep].rename(columns=rename)
    for col in ["营业收入", "毛利润", "净利润", "扣非净利润", "经营现金流", "自由现金流", "总资产", "总负债", "股东权益", "分红金额"]:
        if col in view.columns:
            view[col] = view[col].map(lambda x: format_number_cn(x))
    for col in ["毛利率", "净利率", "ROE", "ROA", "股息率"]:
        if col in view.columns:
            view[col] = view[col].map(lambda x: format_percent(x))
    for col in ["D/E", "EPS", "BVPS"]:
        if col in view.columns:
            view[col] = view[col].map(lambda x: format_price(x))
    return view


def render_financial_table(df: pd.DataFrame) -> None:
    view = _financial_frame(df)
    if view.empty:
        st.info("当前数据源暂未返回可展示的财务表。")
        return
    st.dataframe(view.head(5), hide_index=True, use_container_width=True, height=min(300, 44 + len(view.head(5)) * 38))
    with st.expander("完整财务表 / Debug", expanded=False):
        st.dataframe(view, hide_index=True, use_container_width=True)


def _period_values(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    data = df.copy()
    if "period" in data.columns:
        data["period"] = pd.to_datetime(data["period"], errors="coerce")
        data = data.sort_values("period")
    return data


def plot_financial_revenue_profit(df: pd.DataFrame) -> go.Figure:
    data = _period_values(df)
    fig = go.Figure()
    if data.empty:
        return _base_fig(fig, 340)
    if "totalRevenue" in data.columns:
        fig.add_trace(go.Bar(x=data["period"], y=data["totalRevenue"], name="营业收入", marker_color="rgba(91,140,255,0.65)"))
    if "netIncome" in data.columns:
        fig.add_trace(go.Scatter(x=data["period"], y=data["netIncome"], name="净利润", mode="lines+markers", line=dict(color=GREEN, width=2.4)))
    fig.update_yaxes(title="金额")
    return _base_fig(fig, 350)


def plot_profitability(df: pd.DataFrame) -> go.Figure:
    data = _period_values(df)
    fig = go.Figure()
    for col, name, color in [("roe", "ROE", CYAN), ("roa", "ROA", PURPLE), ("grossMargin", "毛利率", GREEN), ("netMargin", "净利率", ORANGE)]:
        if col in data.columns and data[col].notna().any():
            fig.add_trace(go.Scatter(x=data["period"], y=data[col] * 100, name=name, mode="lines+markers", line=dict(color=color, width=2.2)))
    fig.update_yaxes(title="%")
    return _base_fig(fig, 350)


def plot_cashflow_vs_profit(df: pd.DataFrame) -> go.Figure:
    data = _period_values(df)
    fig = go.Figure()
    if data.empty:
        return _base_fig(fig, 340)
    if "operatingCashFlow" in data.columns:
        fig.add_trace(go.Bar(x=data["period"], y=data["operatingCashFlow"], name="经营现金流", marker_color="rgba(55,232,255,0.62)"))
    if "netIncome" in data.columns:
        fig.add_trace(go.Bar(x=data["period"], y=data["netIncome"], name="净利润", marker_color="rgba(51,214,159,0.58)"))
    fig.update_layout(barmode="group")
    return _base_fig(fig, 350)


def plot_score_distribution(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for col, name, color in [("short_score", "Short", CYAN), ("long_score", "Long", PURPLE)]:
        if col in df.columns:
            fig.add_trace(go.Histogram(x=df[col], name=name, opacity=0.72, marker_color=color, nbinsx=16))
    fig.update_layout(barmode="overlay")
    return _base_fig(fig, 340)


def plot_score_scatter(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if {"short_score", "long_score"}.issubset(df.columns):
        fig.add_trace(
            go.Scatter(
                x=df["short_score"],
                y=df["long_score"],
                mode="markers+text",
                text=df.get("code", pd.Series([""] * len(df))),
                textposition="top center",
                marker=dict(size=14, color=df.get("composite_score", df["short_score"]), colorscale="Turbo", line=dict(color="rgba(255,255,255,0.28)", width=1)),
                hovertext=df.get("name", ""),
                hovertemplate="%{hovertext}<br>Short %{x:.1f}<br>Long %{y:.1f}<extra></extra>",
            )
        )
    fig.update_xaxes(title="Short Score", range=[0, 100])
    fig.update_yaxes(title="Long Score", range=[0, 100])
    return _base_fig(fig, 340)


def _prepare_recent_table(df: pd.DataFrame, rows: int = 10) -> pd.DataFrame:
    view = df.tail(rows).sort_values("date", ascending=False).copy()
    if "amount_est" not in view.columns and {"close", "volume"}.issubset(view.columns):
        view["amount_est"] = view["close"] * view["volume"]
    if "date" in view.columns:
        view["date"] = pd.to_datetime(view["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    rename = {
        "date": "日期",
        "open": "开盘",
        "high": "最高",
        "low": "最低",
        "close": "收盘",
        "adj_close": "复权收盘",
        "volume": "成交量",
        "amount_est": "估算成交额",
        "amount": "成交额",
        "turnover_rate": "换手率",
        "data_source": "数据源",
        "yahoo_code": "Yahoo代码",
    }
    keep = [col for col in ["date", "open", "high", "low", "close", "adj_close", "volume", "amount_est", "amount", "turnover_rate", "data_source"] if col in view.columns]
    view = view[keep].rename(columns=rename)
    for col in ["开盘", "最高", "最低", "收盘", "复权收盘", "换手率"]:
        if col in view.columns:
            view[col] = view[col].map(lambda x: format_price(x))
    for col in ["成交量", "估算成交额", "成交额"]:
        if col in view.columns:
            view[col] = view[col].map(lambda x: format_number_cn(x))
    return view


def render_recent_data_table(df: pd.DataFrame, rows: int = 10) -> None:
    view = _prepare_recent_table(df, rows)
    st.dataframe(view, hide_index=True, use_container_width=True, height=min(420, 44 + len(view) * 38))
    with st.expander("Raw Data / Debug", expanded=False):
        st.dataframe(df.sort_values("date", ascending=False), hide_index=True, use_container_width=True)
