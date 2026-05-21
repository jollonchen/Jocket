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
GLASS_HOVER_BG = "rgba(13,18,28,0.94)"
GLASS_HOVER_BORDER = "rgba(55,232,255,0.45)"
BAR_LINE = "rgba(255,255,255,0.22)"


def _rgba(hex_color: str, alpha: float) -> str:
    value = hex_color.lstrip("#")
    r, g, b = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _bar_marker(color: str, alpha: float = 0.68) -> dict:
    return dict(color=_rgba(color, alpha), line=dict(color=_rgba(color, 0.95), width=1.15))


def _line_style(color: str, width: float = 2.8) -> dict:
    return dict(color=color, width=width, shape="spline", smoothing=0.45)


def _add_glow_line(fig: go.Figure, *, x, y, name: str, color: str, width: float = 2.8, mode: str = "lines", **kwargs) -> None:
    fig.add_trace(
        go.Scatter(
            x=x,
            y=y,
            mode="lines",
            line=dict(color=_rgba(color, 0.18), width=width + 6, shape="spline", smoothing=0.45),
            hoverinfo="skip",
            showlegend=False,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=y,
            mode=mode,
            name=name,
            line=_line_style(color, width),
            marker=dict(size=7, color=color, line=dict(color="rgba(255,255,255,0.28)", width=1)),
            **kwargs,
        )
    )


def load_css(path: str = "assets/styles.css") -> None:
    css_path = Path(path)
    if css_path.exists():
        st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)
        components.html(
            """
            <script>
            (() => {
              const doc = window.parent.document;
              let orb = doc.getElementById("global-cursor-orb");
              if (!orb) {
                orb = doc.createElement("div");
                orb.id = "global-cursor-orb";
                doc.body.appendChild(orb);
              }
              const selector = ".hero-meta-item,.metric-card,.insight-card,.rank-card,.chart-card,.section-card,.profile-card";
              let active = null;
              const enhanceNav = () => {
                const navButtons = [...doc.querySelectorAll("button")].filter((button) => {
                  const text = (button.innerText || button.textContent || "").trim();
                  return ["AI行情", "个股分析", "市场情绪"].includes(text);
                });
                if (navButtons.length < 3) return;
                const nav = navButtons[0].parentElement;
                if (!nav) return;
                nav.dataset.jocketNavEnhanced = "true";

                // Force nav wrapper to be compact (fit-content) regardless of Streamlit flex layout
                const navWrap = doc.querySelector(".st-key-analysis_mode_top");
                if (navWrap) {
                  const vw = window.parent.innerWidth || doc.documentElement.clientWidth || 768;
                  const isMobile = vw <= 768;
                  if (isMobile) {
                    // Mobile: full width so the CSS media query distributes buttons evenly
                    navWrap.style.setProperty("width", "100%", "important");
                    navWrap.style.setProperty("max-width", "100%", "important");
                    navWrap.style.setProperty("flex", "1 1 auto", "important");
                    navWrap.style.setProperty("align-self", "stretch", "important");
                    navWrap.style.setProperty("display", "block", "important");
                  } else {
                    // Desktop: compact width only as wide as the 3 buttons
                    navWrap.style.setProperty("width", "fit-content", "important");
                    navWrap.style.setProperty("max-width", "100%", "important");
                    navWrap.style.setProperty("flex", "0 0 auto", "important");
                    navWrap.style.setProperty("align-self", "flex-start", "important");
                    navWrap.style.setProperty("display", "block", "important");
                  }
                }

                const marker = doc.getElementById("jocket-current-page");
                const currentPage = marker ? marker.getAttribute("data-page") : "";
                navButtons.forEach((item) => {
                  const text = (item.innerText || item.textContent || "").trim();
                  const selected =
                    currentPage === text ||
                    item.getAttribute("aria-checked") === "true" ||
                    item.getAttribute("aria-selected") === "true" ||
                    item.getAttribute("aria-pressed") === "true" ||
                    item.getAttribute("data-selected") === "true" ||
                    !!item.querySelector("input:checked");
                  item.dataset.jocketNavActive = selected ? "true" : "false";
                });
              };
              enhanceNav();
              setInterval(enhanceNav, 120);
              new MutationObserver(enhanceNav).observe(doc.body, { childList: true, subtree: true });
              doc.addEventListener("pointermove", (event) => {
                orb.style.transform = `translate3d(${event.clientX}px, ${event.clientY}px, 0)`;
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


def _fmt_count(value) -> str:
    try:
        return str(int(float(value)))
    except Exception:
        return "-"

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
    title: str | None = None,
    subtitle: str | None = None,
    ai_summary: str | None = None,
) -> None:
    updated_at = updated_at or datetime.now().strftime("%Y-%m-%d %H:%M")
    title = title or "A股智能雷达"
    subtitle = subtitle or "基于最新行情、技术指标和基本面信息生成中文研究视图。"
    
    ai_block = ""
    if ai_summary:
        ai_block = f'<div class="ai-hero-summary"><span class="ai-sparkle">✨</span><span class="ai-summary-text">{escape(str(ai_summary))}</span></div>'

    html = f'<section class="hero-shell"><div class="hero-content"><div><div class="eyebrow">A股智能分析仪表盘</div><h1 class="hero-title">{escape(str(title))}</h1><p class="hero-subtitle">{escape(str(subtitle))}</p>{ai_block}</div><div class="hero-meta-grid"><div class="hero-meta-item"><div class="meta-label">股票代码</div><div class="meta-value">{escape(str(code or "-"))}</div></div><div class="hero-meta-item"><div class="meta-label">状态</div><div class="meta-value">{escape(str(data_source or "-"))}</div></div><div class="hero-meta-item"><div class="meta-label">最新交易日</div><div class="meta-value">{escape(str(latest_date or "-"))}</div></div><div class="hero-meta-item"><div class="meta-label">更新时间</div><div class="meta-value">{escape(str(updated_at))}</div></div></div></div></section>'
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
    icon = {"up": "上行", "down": "下行", "neutral": "实时"}.get(indicator, "实时")
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


def render_glass_dataframe(df: pd.DataFrame, height: int | None = None) -> None:
    if df is None:
        df = pd.DataFrame()
    frame = df.copy()
    max_height = f"max-height:{int(height)}px;" if height else ""
    html = frame.to_html(index=False, escape=True, classes="glass-dataframe-table", border=0)
    st.markdown(f'<div class="glass-table-wrap" style="{max_height}">{html}</div>', unsafe_allow_html=True)


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
        label = "强势"
    elif num >= 60:
        cls = "pill-cyan"
        label = "观察"
    else:
        cls = "pill-orange"
        label = "谨慎"
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
            f'<div class="insight-label">{escape(item.get("label", "观察点"))}</div>'
            f'<div class="insight-title">{escape(item.get("title", "-"))}</div>'
            f'<div class="insight-body">{escape(item.get("body", "-"))}</div>'
            f'<div style="margin-top:14px"><span class="pill {pill_class}">{escape(item.get("badge", "信号"))}</span></div>'
            f'</div>'
        )
    st.markdown('<div class="insight-grid">' + "".join(cards) + "</div>", unsafe_allow_html=True)


def _base_fig(fig: go.Figure, height: int = 420) -> go.Figure:
    fig.update_layout(
        height=height,
        paper_bgcolor=PAPER_BG,
        plot_bgcolor=PLOT_BG,
        font=dict(color=TEXT, family="Inter, system-ui, sans-serif"),
        margin=dict(l=16, r=16, t=46, b=16),
        hovermode="x unified",
        dragmode="pan",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(color=MUTED, size=12),
            bgcolor="rgba(7,11,18,0.20)",
        ),
        hoverlabel=dict(
            bgcolor=GLASS_HOVER_BG,
            bordercolor=GLASS_HOVER_BORDER,
            font=dict(color=TEXT, size=13, family="Inter, system-ui, sans-serif"),
            align="left",
        ),
        transition=dict(duration=250, easing="cubic-in-out"),
    )
    fig.update_xaxes(
        showgrid=True,
        gridcolor="rgba(255,255,255,0.035)",
        zerolinecolor="rgba(255,255,255,0.12)",
        color=MUTED,
        rangeslider_visible=False,
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikecolor="rgba(245,247,250,0.52)",
        spikedash="dot",
        spikethickness=1,
        tickfont=dict(color=MUTED, size=12),
        title_font=dict(color=MUTED, size=13),
    )
    fig.update_yaxes(
        gridcolor="rgba(255,255,255,0.075)",
        zerolinecolor="rgba(255,255,255,0.13)",
        color=MUTED,
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikecolor="rgba(245,247,250,0.42)",
        spikedash="dot",
        spikethickness=1,
        tickfont=dict(color=MUTED, size=12),
        title_font=dict(color=MUTED, size=13),
    )
    return fig


def style_plotly_figure(fig: go.Figure, height: int = 420) -> go.Figure:
    return _base_fig(fig, height)


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
                name="K线",
                increasing=dict(line=dict(color=GREEN, width=1.8), fillcolor="rgba(51,214,159,0.52)"),
                decreasing=dict(line=dict(color=RED, width=1.8), fillcolor="rgba(255,92,122,0.50)"),
                whiskerwidth=0.45,
                hovertext=[
                    f"K线<br>{x}<br>开 {o:.2f}<br>高 {h:.2f}<br>低 {l:.2f}<br>收 {c:.2f}"
                    for x, o, h, l, c in zip(data["date"], data["open"], data["high"], data["low"], data["close"])
                ],
                hoverinfo="text",
            )
        )
    else:
        _add_glow_line(fig, x=data["date"], y=data["close"], name="收盘价", color=CYAN, width=3.0)
    for ma, color in [("ma20", CYAN), ("ma60", BLUE), ("ma120", PURPLE)]:
        if ma in data.columns and data[ma].notna().any():
            _add_glow_line(fig, x=data["date"], y=data[ma], name=ma.upper(), color=color, width=2.35, hovertemplate=f"{ma.upper()}<br>%{{x}}<br>%{{y:.2f}}<extra></extra>")
    return _base_fig(fig, 460)


def plot_market_sentiment_cycle(history: pd.DataFrame) -> go.Figure:
    data = history.tail(90).copy() if history is not None else pd.DataFrame()
    fig = go.Figure()
    if data.empty:
        return _base_fig(fig, 420)
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    missing = pd.to_numeric(data.get("history_missing", 0), errors="coerce").fillna(0)
    counts = (
        pd.to_numeric(data.get("limit_up_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(data.get("broken_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(data.get("limit_down_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(data.get("strong_count", 0), errors="coerce").fillna(0)
    )
    data = data[(missing <= 0) & (counts > 0)].copy()
    if data.empty:
        return _base_fig(fig, 420)
    limit_count = pd.to_numeric(data.get("limit_up_count", 0), errors="coerce").fillna(0)
    broken_count = pd.to_numeric(data.get("broken_count", 0), errors="coerce").fillna(0)
    down_count = pd.to_numeric(data.get("limit_down_count", 0), errors="coerce").fillna(0)
    max_streak = pd.to_numeric(data.get("max_streak", 0), errors="coerce").fillna(0)
    broken_rate = pd.to_numeric(data.get("broken_rate", 0), errors="coerce").fillna(0) * 100
    score = (
        (limit_count / max(limit_count.max(), 1) * 45)
        + (max_streak / max(max_streak.max(), 1) * 25)
        + (pd.to_numeric(data.get("strong_count", 0), errors="coerce").fillna(0) / max(pd.to_numeric(data.get("strong_count", 0), errors="coerce").fillna(0).max(), 1) * 20)
        - broken_rate * 0.18
        - down_count * 1.2
        + 12
    ).clip(0, 100)
    _add_glow_line(fig, x=data["date"], y=score, name="情绪指数", color=RED, width=3.0, mode="lines+markers")
    _add_glow_line(fig, x=data["date"], y=(limit_count / max(limit_count.max(), 1) * 100).clip(0, 100), name="涨停强度", color=PURPLE, width=2.2)
    _add_glow_line(fig, x=data["date"], y=broken_rate.clip(0, 100), name="炸板率", color=ORANGE, width=2.2)
    _add_glow_line(fig, x=data["date"], y=(down_count / max(down_count.max(), 1) * 100).clip(0, 100), name="冰点压力", color=BLUE, width=2.2)
    fig.add_hrect(y0=80, y1=100, fillcolor="rgba(255,92,122,0.08)", line_width=0)
    fig.add_hrect(y0=0, y1=20, fillcolor="rgba(91,140,255,0.10)", line_width=0)
    fig.update_yaxes(title="指数 (0-100)", range=[0, 100])
    fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    return _base_fig(fig, 430)


def plot_market_sentiment_heatmap(heatmap: pd.DataFrame) -> go.Figure:
    data = heatmap.copy() if heatmap is not None else pd.DataFrame()
    fig = go.Figure()
    if data.empty:
        return _base_fig(fig, 430)
    data["date"] = pd.to_datetime(data["date"], errors="coerce").dt.strftime("%m/%d")
    pivot = data.pivot_table(index="board_name", columns="date", values="heat", aggfunc="max", fill_value=0)
    raw = data.pivot_table(index="board_name", columns="date", values="raw_heat", aggfunc="max", fill_value=0).reindex(index=pivot.index, columns=pivot.columns, fill_value=0)
    limits = data.pivot_table(index="board_name", columns="date", values="limit_count", aggfunc="max", fill_value=0).reindex(index=pivot.index, columns=pivot.columns, fill_value=0)
    streaks = data.pivot_table(index="board_name", columns="date", values="max_streak", aggfunc="max", fill_value=0).reindex(index=pivot.index, columns=pivot.columns, fill_value=0)
    seal = data.pivot_table(index="board_name", columns="date", values="seal_fund", aggfunc="max", fill_value=0).reindex(index=pivot.index, columns=pivot.columns, fill_value=0)
    pivot = pivot.loc[pivot.max(axis=1).sort_values(ascending=False).index]
    raw = raw.reindex(index=pivot.index)
    limits = limits.reindex(index=pivot.index)
    streaks = streaks.reindex(index=pivot.index)
    seal = seal.reindex(index=pivot.index)
    custom = np.stack([raw.values, limits.values, streaks.values, seal.values], axis=-1)
    fig.add_trace(
        go.Heatmap(
            z=pivot.values,
            x=pivot.columns,
            y=pivot.index,
            customdata=custom,
            colorscale=[
                [0, "rgba(91,140,255,0.10)"],
                [0.35, "rgba(255,230,109,0.70)"],
                [0.7, "rgba(255,184,107,0.82)"],
                [1, "rgba(255,92,122,0.95)"],
            ],
            colorbar=dict(title="热度"),
            hovertemplate="%{y}<br>%{x}<br>归一化热度 %{z:.1f}<br>原始热度 %{customdata[0]:,.1f}<br>涨停 %{customdata[1]:.0f} 家<br>最高 %{customdata[2]:.0f} 板<br>封板资金 %{customdata[3]:,.0f}<extra></extra>",
        )
    )
    return _base_fig(fig, 470)


def plot_ice_point_month_stats(month_stats: pd.DataFrame) -> go.Figure:
    data = month_stats.copy() if month_stats is not None else pd.DataFrame()
    fig = go.Figure()
    if data.empty:
        return _base_fig(fig, 320)
    fig.add_trace(
        go.Bar(
            x=data["month"],
            y=data["ice_points"],
            name="冰点次数",
            marker=_bar_marker(BLUE, 0.72),
            hovertemplate="%{x}<br>冰点 %{y} 次<extra></extra>",
        )
    )
    fig.update_yaxes(title="次数", rangemode="tozero")
    return _base_fig(fig, 320)


def plot_limit_ecology(history: pd.DataFrame) -> go.Figure:
    data = history.tail(20).copy() if history is not None else pd.DataFrame()
    fig = go.Figure()
    if data.empty:
        return _base_fig(fig, 330)
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    missing = pd.to_numeric(data.get("history_missing", 0), errors="coerce").fillna(0)
    counts = (
        pd.to_numeric(data.get("limit_up_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(data.get("broken_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(data.get("limit_down_count", 0), errors="coerce").fillna(0)
    )
    data = data[(missing <= 0) & (counts > 0)].copy()
    if data.empty:
        return _base_fig(fig, 330)
    fig.add_trace(go.Bar(x=data["date"], y=data.get("limit_up_count", 0), name="涨停", marker=_bar_marker(RED, 0.70)))
    fig.add_trace(go.Bar(x=data["date"], y=data.get("broken_count", 0), name="炸板", marker=_bar_marker(ORANGE, 0.65)))
    fig.add_trace(go.Bar(x=data["date"], y=data.get("limit_down_count", 0), name="跌停", marker=_bar_marker(GREEN, 0.60)))
    fig.update_layout(barmode="group", legend=dict(orientation="h"))
    fig.update_yaxes(title="家数")
    return _base_fig(fig, 340)


def plot_recent_5d_emotion(history: pd.DataFrame) -> go.Figure:
    data = history.copy() if history is not None else pd.DataFrame()
    fig = go.Figure()
    if data.empty:
        return _base_fig(fig, 240)
    missing = pd.to_numeric(data.get("history_missing", 0), errors="coerce").fillna(0)
    counts = (
        pd.to_numeric(data.get("limit_up_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(data.get("broken_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(data.get("limit_down_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(data.get("strong_count", 0), errors="coerce").fillna(0)
    )
    data = data[(missing <= 0) & (counts > 0)].tail(5).copy()
    if data.empty:
        return _base_fig(fig, 240)
    data["date"] = pd.to_datetime(data["date"], errors="coerce").dt.strftime("%m/%d")
    
    limit_count = pd.to_numeric(data.get("limit_up_count", 0), errors="coerce").fillna(0)
    max_streak = pd.to_numeric(data.get("max_streak", 0), errors="coerce").fillna(0)
    strong_count = pd.to_numeric(data.get("strong_count", 0), errors="coerce").fillna(0)
    broken_rate = pd.to_numeric(data.get("broken_rate", 0), errors="coerce").fillna(0) * 100
    down_count = pd.to_numeric(data.get("limit_down_count", 0), errors="coerce").fillna(0)
    
    emotion = (
        (limit_count / max(limit_count.max(), 1) * 45)
        + (max_streak / max(max_streak.max(), 1) * 25)
        + (strong_count / max(strong_count.max(), 1) * 20)
        - broken_rate * 0.18
        - down_count * 1.2
        + 12
    ).clip(0, 100)
    
    _add_glow_line(fig, x=data["date"], y=emotion, name="综合评分", color=RED, width=2.4, mode="lines+markers")
    fig.update_yaxes(title="评分", range=[0, 100])
    fig.update_xaxes(nticks=5)
    return _base_fig(fig, 320)


def plot_recent_5d_limit_counts(history: pd.DataFrame) -> go.Figure:
    data = history.copy() if history is not None else pd.DataFrame()
    fig = go.Figure()
    if data.empty:
        return _base_fig(fig, 240)
    missing = pd.to_numeric(data.get("history_missing", 0), errors="coerce").fillna(0)
    counts = (
        pd.to_numeric(data.get("limit_up_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(data.get("broken_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(data.get("limit_down_count", 0), errors="coerce").fillna(0)
    )
    data = data[(missing <= 0) & (counts > 0)].tail(5).copy()
    if data.empty:
        return _base_fig(fig, 240)
    data["date"] = pd.to_datetime(data["date"], errors="coerce").dt.strftime("%m/%d")
    limit_up = pd.to_numeric(data.get("limit_up_count", pd.Series(0, index=data.index)), errors="coerce").fillna(0)
    broken = pd.to_numeric(data.get("broken_count", pd.Series(0, index=data.index)), errors="coerce").fillna(0)
    limit_down = pd.to_numeric(data.get("limit_down_count", pd.Series(0, index=data.index)), errors="coerce").fillna(0)
    
    fig.add_trace(go.Bar(x=data["date"], y=limit_up, name="涨停", marker=_bar_marker(RED, 0.70)))
    fig.add_trace(go.Bar(x=data["date"], y=broken, name="炸板", marker=_bar_marker(ORANGE, 0.65)))
    fig.add_trace(go.Bar(x=data["date"], y=limit_down, name="跌停", marker=_bar_marker(GREEN, 0.60)))
    fig.update_layout(barmode="group", legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    fig.update_xaxes(nticks=5)
    return _base_fig(fig, 320)


def plot_recent_5d_amount(history: pd.DataFrame) -> go.Figure:
    data = history.copy() if history is not None else pd.DataFrame()
    fig = go.Figure()
    if data.empty:
        return _base_fig(fig, 320)
    missing = pd.to_numeric(data.get("history_missing", 0), errors="coerce").fillna(0)
    counts = (
        pd.to_numeric(data.get("limit_up_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(data.get("broken_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(data.get("limit_down_count", 0), errors="coerce").fillna(0)
    )
    data = data[(missing <= 0) & (counts > 0)].tail(5).copy()
    if data.empty:
        return _base_fig(fig, 320)
    data["date"] = pd.to_datetime(data["date"], errors="coerce").dt.strftime("%m/%d")
    amount = pd.to_numeric(data.get("limit_amount", pd.Series(0, index=data.index)), errors="coerce").fillna(0)
    _add_glow_line(fig, x=data["date"], y=amount / 1_0000_0000, name="涨停成交额(亿)", color=CYAN, width=2.4, mode="lines+markers")
    fig.update_yaxes(title="亿元", rangemode="tozero")
    fig.update_xaxes(nticks=5)
    return _base_fig(fig, 320)


def plot_volume(df: pd.DataFrame) -> go.Figure:
    data = df.tail(120).copy()
    prev_close = data["close"].shift(1)
    colors = np.where(data["close"] >= prev_close, _rgba(GREEN, 0.70), _rgba(RED, 0.70))
    fig = go.Figure(
        go.Bar(
            x=data["date"],
            y=data.get("volume", pd.Series(index=data.index, data=0)),
            marker=dict(color=colors, line=dict(color="rgba(255,255,255,0.18)", width=0.8)),
            name="成交量",
            hovertemplate="%{x}<br>成交量 %{y:,.0f}<extra></extra>",
        )
    )
    return _base_fig(fig, 460)


def plot_price_volume_scatter(df: pd.DataFrame) -> go.Figure:
    data = df.tail(120).copy()
    amount = data.get("amount_est")
    if amount is None:
        amount = data["close"] * data.get("volume", 0)
    size = np.clip((amount.fillna(0) / max(float(amount.fillna(0).max() or 1), 1)) * 34 + 8, 8, 42)
    colors = np.where(data.get("ret_1d", data["close"].pct_change()).fillna(0) >= 0, _rgba(GREEN, 0.72), _rgba(RED, 0.72))
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=data["close"],
            y=amount,
            mode="markers",
            marker=dict(size=size, color=colors, opacity=0.82, line=dict(color="rgba(245,247,250,0.34)", width=1.2)),
            text=data["date"].dt.strftime("%Y-%m-%d") if pd.api.types.is_datetime64_any_dtype(data["date"]) else data["date"].astype(str),
            name="交易日",
            hovertemplate="%{text}<br>收盘价 %{x:.2f}<br>成交额 %{y:,.0f}<extra></extra>",
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
                marker=dict(size=24, color=_rgba(CYAN, 0.88), line=dict(color=TEXT, width=2.2), symbol="diamond"),
                name="最新",
                hovertemplate="最新<br>收盘价 %{x:.2f}<br>成交额 %{y:,.0f}<extra></extra>",
            )
        )
    fig.update_xaxes(title="收盘价")
    fig.update_yaxes(title="成交额")
    return _base_fig(fig, 430)


def plot_rsi(df: pd.DataFrame) -> go.Figure:
    data = df.tail(160).copy()
    fig = go.Figure()
    if "rsi14" in data.columns:
        _add_glow_line(fig, x=data["date"], y=data["rsi14"], name="RSI 14", color=ORANGE, width=2.8, hovertemplate="RSI 14<br>%{x}<br>%{y:.1f}<extra></extra>")
    fig.add_hrect(y0=70, y1=100, fillcolor="rgba(255,92,122,0.12)", line_width=0)
    fig.add_hrect(y0=0, y1=30, fillcolor="rgba(51,214,159,0.12)", line_width=0)
    fig.add_hline(y=70, line_dash="dot", line_color="rgba(255,92,122,0.55)")
    fig.add_hline(y=30, line_dash="dot", line_color="rgba(51,214,159,0.55)")
    fig.update_yaxes(range=[0, 100])
    return _base_fig(fig, 430)


def plot_macd(df: pd.DataFrame) -> go.Figure:
    data = df.tail(160).copy()
    fig = go.Figure()
    if "macd_hist" in data.columns:
        colors = np.where(data["macd_hist"].fillna(0) >= 0, _rgba(GREEN, 0.68), _rgba(RED, 0.68))
        fig.add_trace(go.Bar(x=data["date"], y=data["macd_hist"], marker=dict(color=colors, line=dict(color="rgba(255,255,255,0.16)", width=0.7)), name="柱体"))
    if "macd_diff" in data.columns:
        _add_glow_line(fig, x=data["date"], y=data["macd_diff"], name="DIF", color=CYAN, width=2.4)
    if "macd_dea" in data.columns:
        _add_glow_line(fig, x=data["date"], y=data["macd_dea"], name="DEA", color=PURPLE, width=2.4)
    return _base_fig(fig, 430)


def plot_kdj(df: pd.DataFrame) -> go.Figure:
    data = df.tail(160).copy()
    fig = go.Figure()
    for col, name, color in [("kdj_k", "K", CYAN), ("kdj_d", "D", PURPLE), ("kdj_j", "J", ORANGE)]:
        if col in data.columns:
            _add_glow_line(fig, x=data["date"], y=data[col], name=name, color=color, width=2.4)
    return _base_fig(fig, 430)


def plot_score_breakdown(score_detail: dict, title: str = "评分拆解") -> go.Figure:
    labels = list(score_detail.keys()) or ["评分"]
    values = [float(score_detail.get(label, 0) or 0) for label in labels]
    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker=dict(
                color=values,
                colorscale=[[0, _rgba(RED, 0.82)], [0.5, _rgba(BLUE, 0.82)], [1, _rgba(GREEN, 0.82)]],
                line=dict(color=BAR_LINE, width=1.1),
            ),
            hovertemplate="%{y}<br>评分 %{x:.1f}<extra></extra>",
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
            marker=dict(color="rgba(255,255,255,0.08)", line=dict(color="rgba(255,255,255,0.14)", width=1)),
            name="满分",
            hovertemplate="%{y}<br>满分 %{x:.1f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            x=data["score"],
            y=data["dimension"],
            orientation="h",
            marker=dict(color=data["score_rate"], colorscale=[[0, _rgba(RED, 0.88)], [0.55, _rgba(BLUE, 0.88)], [1, _rgba(GREEN, 0.88)]], line=dict(color=BAR_LINE, width=1.1)),
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
            line=dict(color=CYAN, width=2.8),
            fillcolor="rgba(55,232,255,0.20)",
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
            connector={"line": {"color": "rgba(255,255,255,0.28)", "width": 1}},
            increasing={"marker": {"color": _rgba(GREEN, 0.76), "line": {"color": GREEN, "width": 1}}},
            decreasing={"marker": {"color": _rgba(RED, 0.76), "line": {"color": RED, "width": 1}}},
            totals={"marker": {"color": _rgba(CYAN, 0.82), "line": {"color": CYAN, "width": 1.2}}},
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
            marker=dict(color=_rgba(ORANGE, 0.75), line=dict(color=_rgba(ORANGE, 0.98), width=1.1)),
            hovertemplate="%{y}<br>扣分/缺口 %{x:.1f}<extra></extra>",
        )
    )
    fig.update_layout(title=dict(text=title, font=dict(size=15, color=TEXT)), yaxis=dict(autorange="reversed"))
    return _base_fig(fig, 360)


def format_evidence_value(key: str, value) -> str:
    if value is None or value == "":
        return "暂未获取"
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
        "macd_hist": "MACD 柱体",
        "kdj_k": "KDJ K",
        "kdj_d": "KDJ D",
        "kdj_j": "KDJ J",
        "high_20d": "近20日最高价",
        "distance_to_20d_high": "距20日高点",
        "distance_to_ma20": "距MA20偏离",
        "volatility_60d": "60日波动率",
        "max_drawdown_60d": "60日最大回撤",
        "history_days": "历史样本天数",
        "industry": "行业",
        "industry_cn": "中文行业/主板块",
        "sector": "海外行业分类",
        "belong_boards": "所属板块/概念",
        "top_board": "最强所属板块",
        "top_board_pct": "最强板块涨幅",
        "avg_top3_board_pct": "前三板块均涨幅",
        "positive_board_count": "上涨板块数",
        "board_net_flow_sum": "匹配板块资金净额",
    }
    rows = [
        {"指标": label, "数值": format_evidence_value(key, evidence.get(key))}
        for key, label in labels.items()
        if key in evidence
    ]
    render_glass_dataframe(pd.DataFrame(rows), height=420)


def render_dimension_cards(breakdown: list[dict], namespace: str = "score") -> None:
    for idx, item in enumerate(breakdown):
        title = f"{item.get('dimension', '-')}: {format_price(item.get('score'), 1)} / {format_price(item.get('max_score'), 0)}"
        with st.expander(title, expanded=idx == 0):
            rate = float(item.get("score_rate", 0) or 0)
            if rate >= 0.78:
                stance = "该维度当前是明显贡献项，可以提高研究优先级，但仍要和风险项一起看。"
            elif rate >= 0.55:
                stance = "该维度提供中等支撑，结论偏观察，需要等待其他维度共振。"
            elif rate >= 0.35:
                stance = "该维度贡献有限，暂时不适合作为主要买点依据。"
            else:
                stance = "该维度是当前拖累项，需要优先排查数据背后的风险。"
            positives = [str(x) for x in item.get("positive_factors", []) if x]
            negatives = [str(x) for x in item.get("negative_factors", []) if x]
            driver = positives[0] if positives else "暂无明确正向驱动"
            drag = negatives[0] if negatives else "暂无显著扣分项"
            st.markdown(f"**本轮结论：** {stance} 关键驱动是：{driver}；主要约束是：{drag}")
            st.markdown(f"**评分逻辑：** {item.get('logic', '-')}")
            st.markdown(f"**权重：** {float(item.get('weight', 0) or 0):.0%}　**得分率：** {float(item.get('score_rate', 0) or 0):.1%}")
            st.markdown("**关键数据：**")
            data_points = item.get("data_points", {}) or {}
            rows = [{"数据项": key, "当前值": format_evidence_value(key, value)} for key, value in data_points.items()]
            render_glass_dataframe(pd.DataFrame(rows), height=min(260, 44 + 36 * max(1, len(rows))))
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
    ]
    badges_html = "".join(
        f'<span class="pill pill-cyan">{escape(label)} · {escape(str(value or "暂未获取"))}</span>'
        for label, value in left_badges
    )
    # Format list date if it's in YYYYMMDD string format
    list_date = profile.get("list_date") or ""
    s_date = str(list_date)
    if len(s_date) == 8 and s_date.isdigit():
        list_date = f"{s_date[:4]}-{s_date[4:6]}-{s_date[6:]}"

    kv = [
        ("交易所", profile.get("exchange")),
        ("上市时间", list_date),
        ("总市值", format_number_cn(profile.get("market_cap")) if profile.get("market_cap") else "暂未获取"),
        ("流通市值", format_number_cn(profile.get("float_market_cap")) if profile.get("float_market_cap") else "暂未获取"),
        ("总股本", format_number_cn(profile.get("shares_outstanding")) if profile.get("shares_outstanding") else "暂未获取"),
        ("流通股本", format_number_cn(profile.get("float_shares")) if profile.get("float_shares") else "暂未获取"),
        ("最新收盘价", format_price(profile.get("latest_price")) if profile.get("latest_price") else "暂未获取"),
        ("数据更新", profile.get("updated_at")),
        ("员工数", format_number_cn(profile.get("employees"), 0) if profile.get("employees") else "暂未获取"),
        ("海外行业分类", profile.get("sector")),
    ]
    kv_html = "".join(
        f'<div class="profile-kv"><span>{escape(label)}</span><strong>{escape(str(value or "暂未获取"))}</strong></div>'
        for label, value in kv
    )
    business = profile.get("business") or "暂未获取"
    # Prioritise the passed summary (which should be the translated/curated business intro)
    display_summary = summary or str(business)
    if len(str(display_summary)) > 1200:
        display_summary = str(display_summary)[:1200] + "..."

    html = f"""
    <div class="profile-card">
      <div class="profile-main">
        <div class="eyebrow">公司画像</div>
        <h3>{escape(str(profile.get("name") or profile.get("code") or "-"))}</h3>
        <div class="profile-code">{escape(str(profile.get("code") or "-"))} · {escape(str(profile.get("yahoo_code") or "-"))}</div>
        <div class="profile-badges">{badges_html}</div>
        <div class="profile-summary-text">{escape(display_summary)}</div>
      </div>
      <div class="profile-kv-grid">{kv_html}</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)
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

    def metric_note(label, raw, key, base_note, status_label):
        if raw is None:
            return f"{base_note} · 暂缺该项，结论降权"
        try:
            num = float(raw)
        except Exception:
            return f"{base_note} · {status_label}"
        if key == "pe":
            if num <= 0:
                return "盈利口径为负或异常，PE 暂不适合单独判断"
            if num <= 25:
                return "盈利定价不算激进，继续看增长和行业分位"
            if num <= 45:
                return "估值需要业绩兑现支撑，追高容错变低"
            return "PE 已偏高，短线催化强度要足以覆盖估值压力"
        if key == "pb":
            if num <= 1:
                return "账面估值偏低，需确认资产质量和盈利弹性"
            if num <= 3:
                return "PB 处于可解释区间，关键看 ROE 能否匹配"
            return "PB 偏高，若 ROE 不强则估值性价比下降"
        if key == "ps":
            if num <= 2:
                return "收入估值较克制，适合继续核对毛利和利润率"
            if num <= 6:
                return "收入估值中性，需看收入增速能否延续"
            return "收入估值偏高，增长放缓时回撤弹性会放大"
        if key == "dy":
            if num >= 0.04:
                return "股息提供一定安全垫，更适合耐心跟踪"
            if num >= 0.015:
                return "分红贡献中等，主要回报仍取决于价格和业绩"
            return "股息保护较弱，研究重点应放在增长和趋势"
        if key == "roe":
            if num >= 0.15:
                return "ROE 较强，说明权益资本回报对估值有支撑"
            if num >= 0.08:
                return "ROE 中等，需要结合 PB 判断是否匹配"
            return "ROE 偏弱，中长期吸引力需要其他优势补足"
        if key == "roa":
            if num >= 0.07:
                return "ROA 较强，资产使用效率对质量评分有贡献"
            if num >= 0.03:
                return "ROA 中性，质量结论还要看杠杆和现金流"
            return "ROA 偏弱，说明资产盈利效率仍需验证"
        if key == "de":
            if num < 1:
                return "杠杆压力较轻，基本面风险项相对温和"
            if num <= 2:
                return "杠杆中等，需继续看现金流覆盖能力"
            return "杠杆偏高，中长期结论必须加入风控折扣"
        return f"{base_note} · {status_label}"

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
        cards.append(metric_card(label, value, metric_note(label, raw, key, note, status_label), tone, "neutral"))
    render_bento_grid(cards)


def plot_ratings_snapshot(ratings: dict) -> go.Figure:
    scores = ratings.get("scores", {}) if ratings else {}
    usable = {key: value for key, value in scores.items() if key != "DCF" and value is not None}
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
            name="评级",
            line=dict(color=CYAN, width=2.8),
            marker=dict(size=7, color=CYAN, line=dict(color="rgba(255,255,255,0.30)", width=1)),
            fillcolor="rgba(55,232,255,0.20)",
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
        "ROE": "净资产收益率",
        "ROA": "总资产收益率",
        "D/E": "债务权益比",
        "P/E": "市盈率",
        "P/B": "市净率",
        "Dividend Yield": "股息率",
        "Revenue Growth": "收入增长",
        "Net Profit Growth": "净利润增长",
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
        + f'<div class="rating-overall"><span>综合评分</span><strong>{escape("N/A" if overall is None else f"{overall:.1f}")}</strong><em>{escape(str(rating))}</em></div>'
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
        st.info("暂未取得可展示的财务表。")
        return
    with st.expander("完整财务表", expanded=False):
        render_glass_dataframe(view)


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
        fig.add_trace(go.Bar(x=data["period"], y=data["totalRevenue"], name="营业收入", marker=_bar_marker(BLUE, 0.62), hovertemplate="%{x|%Y-%m-%d}<br>营业收入 %{y:,.0f}<extra></extra>"))
    if "netIncome" in data.columns:
        _add_glow_line(fig, x=data["period"], y=data["netIncome"], name="净利润", color=GREEN, width=2.8, mode="lines+markers", hovertemplate="%{x|%Y-%m-%d}<br>净利润 %{y:,.0f}<extra></extra>")
    fig.update_yaxes(title="金额")
    return _base_fig(fig, 350)


def plot_profitability(df: pd.DataFrame) -> go.Figure:
    data = _period_values(df)
    fig = go.Figure()
    for col, name, color in [("roe", "ROE", CYAN), ("roa", "ROA", PURPLE), ("grossMargin", "毛利率", GREEN), ("netMargin", "净利率", ORANGE)]:
        if col in data.columns and data[col].notna().any():
            _add_glow_line(fig, x=data["period"], y=data[col] * 100, name=name, color=color, width=2.6, mode="lines+markers", hovertemplate=f"{name}<br>%{{x|%Y-%m-%d}}<br>%{{y:.2f}}%<extra></extra>")
    fig.update_yaxes(title="%")
    return _base_fig(fig, 350)


def plot_cashflow_vs_profit(df: pd.DataFrame) -> go.Figure:
    data = _period_values(df)
    fig = go.Figure()
    if data.empty:
        return _base_fig(fig, 340)
    if "operatingCashFlow" in data.columns:
        fig.add_trace(go.Bar(x=data["period"], y=data["operatingCashFlow"], name="经营现金流", marker=_bar_marker(CYAN, 0.62), hovertemplate="%{x|%Y-%m-%d}<br>经营现金流 %{y:,.0f}<extra></extra>"))
    if "netIncome" in data.columns:
        fig.add_trace(go.Bar(x=data["period"], y=data["netIncome"], name="净利润", marker=_bar_marker(GREEN, 0.58), hovertemplate="%{x|%Y-%m-%d}<br>净利润 %{y:,.0f}<extra></extra>"))
    fig.update_layout(barmode="group")
    return _base_fig(fig, 350)


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


def _render_emotion_cycle_position(metrics: dict) -> None:
    period = metrics.get("period", "周期待确认")
    phases = ["退潮", "冰点", "常态", "启动", "发酵", "高潮"]
    
    html = '<div class="sentiment-cycle-timeline" style="display:flex; justify-content:space-between; align-items:center; margin: 16px 0 24px; position:relative;">\n'
    html += '<div style="position:absolute; top:50%; left:5%; right:5%; height:2px; background:rgba(255,255,255,0.1); z-index:0;"></div>\n'
    
    for phase in phases:
        is_active = (phase == period)
        color = "var(--accent-red)" if is_active else "rgba(255,255,255,0.3)"
        bg = "rgba(255,92,122,0.2)" if is_active else "rgba(255,255,255,0.05)"
        border = f"2px solid {color}" if is_active else f"1px solid {color}"
        weight = "900" if is_active else "500"
        shadow = "0 0 16px rgba(255,92,122,0.4)" if is_active else "none"
        
        html += f'<div style="display:flex; flex-direction:column; align-items:center; z-index:1; gap:8px;">\n'
        html += f'<div style="width:16px; height:16px; border-radius:50%; background:{bg}; border:{border}; box-shadow:{shadow};"></div>\n'
        html += f'<span style="color:{color}; font-size:0.85rem; font-weight:{weight};">{phase}</span>\n'
        html += f'</div>\n'
    html += '</div>\n'
    
    # 4 small metrics with explicit reference bands.
    short = metrics.get("short_emotion") or 0
    big = metrics.get("big_market_factor") or 0
    div = abs(short - big)
    broken_rate = (metrics.get("broken_rate") or 0) * 100
    limit = metrics.get("limit_up_count", 0)
    down = metrics.get("limit_down_count", 0)
    broken = metrics.get("broken_count", 0)
    amount_yi = (metrics.get("market_amount") or 0) / 100000000

    def mini_card(label: str, value: str, note: str, width: float, tone: str) -> str:
        safe_width = max(0, min(100, width))
        return (
            f'<div class="mini-metric sentiment-mini {tone}">'
            f'<span>{label}</span>'
            f'<strong>{value}</strong>'
            f'<div class="sentiment-strength {tone}"><i style="width:{safe_width:.1f}%"></i></div>'
            f'<small>{note}</small>'
            f'</div>\n'
        )
    
    html += '<div class="sentiment-cycle-metrics">\n'
    div_tone = "danger" if div >= 25 else "warning" if div >= 14 else "watch"
    html += mini_card("大小盘分歧", format_price(div, 1), f"超短 {format_price(short, 1)} / 宽度 {format_price(big, 1)}，低于 14 更顺。", min(div / 30 * 100, 100), div_tone)
    broken_tone = "danger" if broken_rate >= 35 else "warning" if broken_rate >= 25 else "watch"
    html += mini_card("炸板压力", f"{format_price(broken_rate, 1)}%", f"炸板 {int(broken or 0)} 家，25% 以上代表分歧抬升。", min(broken_rate / 40 * 100, 100), broken_tone)
    eco_tone = "good" if limit >= 60 and down <= 5 else "warning" if down >= 8 else "watch"
    html += mini_card("涨跌停生态", f"{_fmt_count(limit)} / {_fmt_count(down)}", "涨停 / 跌停，观察赚钱效应是否扩散。", min((limit or 0) / 90 * 100, 100), eco_tone)
    amount_tone = "good" if amount_yi >= 10000 else "watch" if amount_yi >= 7000 else "cool"
    html += mini_card("两市成交额", f"{format_price(amount_yi, 0)}亿", "万亿以上更利于主线持续，缩量时降低预期。", min(amount_yi / 12000 * 100, 100), amount_tone)
    
    html += '</div>\n'
    
    st.markdown(html, unsafe_allow_html=True)


def plot_score_distribution(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for col, name, color in [("short_score", "短线", CYAN), ("long_score", "中长线", PURPLE)]:
        if col in df.columns:
            fig.add_trace(go.Histogram(x=df[col], name=name, opacity=0.70, marker=_bar_marker(color, 0.64), nbinsx=16))
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
                marker=dict(size=15, color=df.get("composite_score", df["short_score"]), colorscale=[[0, RED], [0.55, BLUE], [1, GREEN]], opacity=0.88, line=dict(color="rgba(245,247,250,0.34)", width=1.2)),
                hovertext=df.get("name", ""),
                hovertemplate="%{hovertext}<br>短线 %{x:.1f}<br>中长线 %{y:.1f}<extra></extra>",
            )
        )
    fig.update_xaxes(title="短线评分", range=[0, 100])
    fig.update_yaxes(title="中长线评分", range=[0, 100])
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
        "yahoo_code": "Yahoo代码",
    }
    keep = [col for col in ["date", "open", "high", "low", "close", "adj_close", "volume", "amount_est", "amount", "turnover_rate"] if col in view.columns]
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
    render_glass_dataframe(view, height=min(420, 44 + len(view) * 38))
    with st.expander("Raw Data", expanded=False):
        render_glass_dataframe(df.sort_values("date", ascending=False))
