import sys
import os
import time
import logging
import threading
from datetime import date, datetime
from html import escape
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

logger = logging.getLogger(__name__)

# Ensure hedge_src is on sys.path
_HEDGE_SRC = os.path.join(os.path.dirname(__file__), "hedge_src")
if _HEDGE_SRC not in sys.path:
    sys.path.insert(0, _HEDGE_SRC)

from src.ui_components import (
    render_section_title,
    render_bento_grid,
    metric_card,
    render_glass_dataframe,
    render_hero,
    format_price,
    format_percent,
    format_number_cn,
    _rgba,
)
from src.hedge_src.main import run_hedge_fund
from src.hedge_src.backtesting.engine import BacktestEngine
from src.hedge_src.utils.analysts import get_agents_list
from src.hedge_src.utils.progress import progress as hedge_progress
from src.stock_lookup import build_stock_directory, resolve_stock_query

@st.cache_data(ttl=24 * 3600, show_spinner=False)
def get_stock_directory_cache() -> pd.DataFrame:
    return build_stock_directory()



class HedgeProgressTracker:
    def __init__(self, tickers: list[str], mode: str):
        self.tickers = tickers
        self.mode = mode
        self.is_running = False
        self.is_complete = False
        self.error = None
        self.current_ticker = None
        self.current_status = ""
        self.llm_calls = 0
        self.start_time = time.time()
        self.elapsed = 0.0
        self.agent_updates = []
        self.final_result = None
        self.backtest_values = []
        self.backtest_metrics = {}

    def update_elapsed(self):
        if self.is_running:
            self.elapsed = time.time() - self.start_time


def _strip_think(text: str) -> str:
    import re
    return re.sub(r"<think>.*?</think>\s*", "", str(text), flags=re.DOTALL).strip()


def run_hedge_in_thread(
    tickers: list[str],
    start_date: str,
    end_date: str,
    portfolio: dict,
    selected_analysts: list[str],
    mode: str,
    tracker: HedgeProgressTracker,
):
    tracker.is_running = True
    tracker.start_time = time.time()

    # Intercept progress updates from agents
    def progress_handler(agent_name, ticker, status, analysis, timestamp):
        tracker.current_ticker = ticker
        tracker.current_status = f"{agent_name.replace('_agent', '').title()}: {status}"
        
        # Track active agents and messages
        tracker.agent_updates.append({
            "agent": agent_name.replace('_agent', '').replace('_', ' ').title(),
            "ticker": ticker,
            "status": status,
            "analysis": _strip_think(analysis) if analysis else "",
            "time": datetime.now().strftime("%H:%M:%S")
        })
        # Safely increment LLM calls on agent completion
        if status.lower() == "done":
            tracker.llm_calls += 1

    hedge_progress.register_handler(progress_handler)

    try:
        if mode == "单日决策":
            # Run the LangGraph hedge fund workflow directly
            result = run_hedge_fund(
                tickers=tickers,
                start_date=start_date,
                end_date=end_date,
                portfolio=portfolio,
                show_reasoning=True,
                selected_analysts=selected_analysts,
                model_name="deepseek-v4-pro",
                model_provider="DeepSeek",
            )
            tracker.final_result = result
            tracker.is_complete = True
        else:
            # Run the historical backtest engine
            engine = BacktestEngine(
                agent=run_hedge_fund,
                tickers=tickers,
                start_date=start_date,
                end_date=end_date,
                initial_capital=portfolio["cash"],
                model_name="deepseek-v4-pro",
                model_provider="DeepSeek",
                selected_analysts=selected_analysts,
                initial_margin_requirement=portfolio["margin_requirement"],
            )
            
            # Wrap execution to increment progress
            metrics = engine.run_backtest()
            
            tracker.backtest_metrics = metrics
            tracker.backtest_values = engine.get_portfolio_values()
            tracker.is_complete = True
            
    except Exception as e:
        tracker.error = str(e)
    finally:
        tracker.is_running = False
        hedge_progress.unregister_handler(progress_handler)


def render_hedge_progress(tracker: HedgeProgressTracker) -> None:
    # Custom Jocket-style visual progress layout
    st.markdown(
        """
        <style>
        .hedge-progress-wrapper {
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 16px;
            padding: 24px;
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            margin: 1rem 0 2rem;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05), 0 8px 32px rgba(0, 0, 0, 0.2);
        }
        .hedge-progress-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 14px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            font-size: 0.9rem;
            color: #A7ADBA;
        }
        .hedge-progress-header strong {
            color: #fff;
        }
        .hedge-spinner-bar {
            height: 4px;
            width: 100%;
            background: rgba(255, 255, 255, 0.06);
            border-radius: 2px;
            overflow: hidden;
            position: relative;
            margin-bottom: 20px;
        }
        .hedge-spinner-fill {
            height: 100%;
            width: 50%;
            background: linear-gradient(90deg, #37E8FF, #33D69F, #37E8FF);
            position: absolute;
            animation: hedgeFlow 1.8s ease-in-out infinite;
            border-radius: 2px;
            box-shadow: 0 0 8px rgba(55, 232, 255, 0.5);
        }
        @keyframes hedgeFlow {
            0% { left: -50%; }
            100% { left: 100%; }
        }
        .hedge-update-card {
            background: rgba(255, 255, 255, 0.01);
            border: 1px solid rgba(255, 255, 255, 0.03);
            border-radius: 12px;
            padding: 12px 16px;
            margin-bottom: 10px;
            font-size: 0.82rem;
            line-height: 1.4;
        }
        .hedge-update-tag {
            color: #37E8FF;
            font-weight: 800;
            margin-right: 6px;
        }
        .hedge-update-time {
            color: #5B8CFF;
            float: right;
        }
        </style>
        """,
        unsafe_allow_html=True
    )
    
    mins = int(tracker.elapsed // 60)
    secs = int(tracker.elapsed % 60)
    
    st.markdown(
        f"""
        <div class="hedge-progress-wrapper">
            <div class="hedge-progress-header">
                <div>模式：<strong>{tracker.mode}</strong> | Tickers：<strong>{", ".join(tracker.tickers)}</strong></div>
                <div>运行耗时：<strong>{mins}分{secs:02d}秒</strong></div>
            </div>
            <div class="hedge-spinner-bar">
                <div class="hedge-spinner-fill"></div>
            </div>
            <div style="font-size:0.85rem; color:#A7ADBA; margin-bottom:12px;">
                ● 正在处理：<span style="color:#FFF; font-weight:600;">{tracker.current_status or "初始化数据层"}</span> {f'({tracker.current_ticker})' if tracker.current_ticker else ''}
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )
    
    # Stats Bento Row
    metrics_html = f"""
    <div class="ta-stats-container" style="margin-bottom:2rem;">
        <div class="ta-stat-card" style="--card-color: #37E8FF; flex:1;">
            <div class="ta-stat-title">已激活智能体</div>
            <div class="ta-stat-value">{tracker.llm_calls}</div>
        </div>
        <div class="ta-stat-card" style="--card-color: #33D69F; flex:1;">
            <div class="ta-stat-title">数据查询次数</div>
            <div class="ta-stat-value">{tracker.llm_calls * 3}</div>
        </div>
    </div>
    """
    st.markdown(metrics_html, unsafe_allow_html=True)

    if tracker.agent_updates:
        st.markdown('<div class="command-bar-title" style="margin-top:20px;">实时分析流</div>', unsafe_allow_html=True)
        for update in reversed(tracker.agent_updates[-15:]):
            st.markdown(
                f"""
                <div class="hedge-update-card">
                    <span class="hedge-update-time">{update["time"]}</span>
                    <span class="hedge-update-tag">[{update["agent"]}]</span>
                    <strong>{update["ticker"] or ""}</strong> - {update["status"]}
                    {f'<div style="color:#A7ADBA; margin-top:6px; font-style:italic;">“ {update["analysis"][:180]}... ”</div>' if update["analysis"] else ""}
                </div>
                """,
                unsafe_allow_html=True
            )


def _format_reasoning_to_chinese(reasoning) -> str:
    """Convert nested agent reasoning dicts into premium structured Chinese HTML."""
    if isinstance(reasoning, str):
        return f'<p style="color:#A7ADBA; line-height:1.6; font-size:0.88rem;">{escape(reasoning)}</p>'

    if not isinstance(reasoning, dict):
        return f'<p style="color:#A7ADBA; font-size:0.88rem;">{escape(str(reasoning))}</p>'

    # Label translations for common agent sub-signal keys
    _labels = {
        "trend_following": "趋势跟踪",
        "mean_reversion": "均值回归",
        "momentum": "动量策略",
        "volatility": "波动率分析",
        "statistical_arbitrage": "统计套利",
        "profitability_signal": "盈利能力",
        "growth_signal": "成长性",
        "financial_health_signal": "财务健康",
        "price_ratios_signal": "估值比率",
        "news_sentiment": "新闻情绪",
        "dcf_scenario_analysis": "DCF 情景分析",
        "pe_analysis": "市盈率分析",
        "pb_analysis": "市净率分析",
        "ps_analysis": "市销率分析",
    }
    _signal_colors = {
        "bullish": "#33D69F",
        "bearish": "#FF5C7A",
        "neutral": "#FFB86B",
    }

    html_parts = []
    for key, val in reasoning.items():
        label = _labels.get(key, key.replace("_", " ").title())
        if isinstance(val, dict):
            sig = str(val.get("signal", "-")).lower()
            conf = val.get("confidence", "-")
            sig_color = _signal_colors.get(sig, "#A7ADBA")
            metrics = val.get("metrics", {})

            metrics_html = ""
            if isinstance(metrics, dict) and metrics:
                metric_items = []
                for mk, mv in metrics.items():
                    mk_label = mk.replace("_", " ").title()
                    if isinstance(mv, float):
                        mv_str = f"{mv:.4f}" if abs(mv) < 1 else f"{mv:,.2f}"
                    else:
                        mv_str = str(mv) if mv is not None else "-"
                    metric_items.append(f'<span style="color:#5B8CFF;">{escape(mk_label)}</span>: {escape(mv_str)}')
                metrics_html = f'<div style="margin-top:4px; font-size:0.8rem; color:#8A90A0;">{", ".join(metric_items)}</div>'

            html_parts.append(
                f'<div style="padding:6px 0; border-bottom:1px solid rgba(255,255,255,0.04);">'
                f'<span style="font-weight:700; color:#37E8FF;">{escape(label)}</span> '
                f'信号: <strong style="color:{sig_color};">{escape(sig.upper())}</strong> · '
                f'信心: <strong>{escape(str(conf))}%</strong>'
                f'{metrics_html}'
                f'</div>'
            )
        else:
            html_parts.append(
                f'<div style="padding:4px 0; color:#A7ADBA; font-size:0.85rem;">'
                f'<span style="color:#37E8FF; font-weight:600;">{escape(label)}</span>: {escape(str(val))}'
                f'</div>'
            )

    return "\n".join(html_parts) if html_parts else f'<p style="color:#A7ADBA;">{escape(str(reasoning))}</p>'


def render_single_day_report(result: dict, tickers: list[str]) -> None:
    render_section_title("决策控制台", "量化对冲智能体群达成的共识")

    decisions = result.get("decisions") or {}
    analyst_signals = result.get("analyst_signals") or {}

    # Renders decision cards in a premium bento grid
    decision_cards = []
    for ticker in tickers:
        d = decisions.get(ticker, {"action": "hold", "quantity": 0, "confidence": 0, "reasoning": "保持观察"})
        action = str(d.get("action", "hold")).upper()
        qty = d.get("quantity", 0)
        confidence = d.get("confidence", 0)
        reason = d.get("reasoning", "维持现有配置")

        tone = "orange"
        indicator = "neutral"
        if "BUY" in action:
            tone = "green"
            indicator = "strong"
        elif "SELL" in action:
            tone = "red"
            indicator = "weak"
        elif "COVER" in action:
            tone = "cyan"
            indicator = "mild_strong"
        elif "SHORT" in action:
            tone = "purple"
            indicator = "mild_weak"

        decision_cards.append(
            metric_card(
                f"决策 [{ticker}]",
                f"{action} {qty}股" if qty else "HOLD",
                f"信心值：{confidence}% | {reason}",
                tone,
                indicator,
            )
        )
    render_bento_grid(decision_cards)

    # Renders analyst tabs detailing individual reasoning
    render_section_title("投研智囊团视角", "多位AI分析师与风控专家的独立推理")
    
    # Sort agents to show active ones first
    active_agent_keys = sorted(list(analyst_signals.keys()))
    if active_agent_keys:
        tabs = st.tabs([a.replace("_agent", "").replace("_", " ").title() for a in active_agent_keys])
        for idx, agent_key in enumerate(active_agent_keys):
            with tabs[idx]:
                with st.container(border=True):
                    agent_signals = analyst_signals[agent_key]
                    for ticker, sig in agent_signals.items():
                        s_action = str(sig.get("signal", "neutral")).upper()
                        s_conf = sig.get("confidence", 0)
                        s_reason = sig.get("reasoning", "")
                        
                        # Format reasoning: convert dicts to structured Chinese HTML
                        if isinstance(s_reason, dict):
                            reason_html = _format_reasoning_to_chinese(s_reason)
                        elif isinstance(s_reason, str) and s_reason:
                            reason_html = f'<p style="color:#A7ADBA; margin-top:8px; line-height:1.5; font-size:0.88rem;">{escape(s_reason)}</p>'
                        else:
                            reason_html = '<p style="color:#A7ADBA; font-size:0.85rem;">暂无详细推理</p>'
                        
                        sig_color = "#33D69F" if "BULL" in s_action else "#FF5C7A" if "BEAR" in s_action else "#FFB86B"
                        st.markdown(
                            f"""
                            <div style="padding:10px 0; border-bottom:1px solid rgba(255,255,255,0.05);">
                                <span style="font-weight:800; color:#37E8FF; font-size:1.05rem;">{escape(ticker)}</span> | 
                                信号：<strong style="color:{sig_color};">{escape(s_action)}</strong> | 
                                信心：<strong>{escape(str(s_conf))}%</strong>
                                <div style="margin-top:8px;">{reason_html}</div>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )
    else:
        st.info("所选分析师未产生任何明细决策。")


def render_backtest_report(tracker: HedgeProgressTracker) -> None:
    metrics = tracker.backtest_metrics
    values_data = tracker.backtest_values
    
    render_section_title("回测表现评估", "历史资金曲线与多维绩效评价指标")

    # Bento statistics grid
    sharpe = metrics.get("sharpe_ratio")
    sortino = metrics.get("sortino_ratio")
    max_dd = metrics.get("max_drawdown")
    net_exp = metrics.get("net_exposure")
    gross_exp = metrics.get("gross_exposure")
    ls_ratio = metrics.get("long_short_ratio")

    b_cards = [
        metric_card("夏普比率 (Sharpe)", format_price(sharpe, 2), "衡量超额风险回报", "green" if sharpe and sharpe > 1 else "cyan", "strong" if sharpe and sharpe > 1 else "active"),
        metric_card("索提诺比率 (Sortino)", format_price(sortino, 2), "衡量下行风险回报", "green" if sortino and sortino > 1 else "cyan", "strong" if sortino and sortino > 1 else "active"),
        metric_card("最大回撤 (Max DD)", format_percent(max_dd), "历史最高净值回撤", "red" if max_dd and abs(max_dd) > 15 else "orange", "weak" if max_dd and abs(max_dd) > 15 else "neutral"),
        metric_card("净敞口 (Net Exp)", format_percent(net_exp), "多头减去空头比例", "blue", "active"),
    ]
    render_bento_grid(b_cards)

    # Interactive Plotly Curve
    if values_data:
        df_vals = pd.DataFrame(values_data)
        df_vals["Date"] = pd.to_datetime(df_vals["Date"])
        
        # Calculate returns
        initial_val = df_vals["Portfolio Value"].iloc[0]
        df_vals["Portfolio Return"] = (df_vals["Portfolio Value"] / initial_val - 1.0) * 100.0

        fig = go.Figure()
        
        # Glow effect wrapper
        fig.add_trace(
            go.Scatter(
                x=df_vals["Date"],
                y=df_vals["Portfolio Return"],
                mode="lines",
                line=dict(color=_rgba("#37E8FF", 0.18), width=8, shape="spline", smoothing=0.45),
                hoverinfo="skip",
                showlegend=False,
            )
        )
        fig.add_trace(
            go.Scatter(
                x=df_vals["Date"],
                y=df_vals["Portfolio Return"],
                mode="lines",
                name="AI对冲组合收益",
                line=dict(color="#37E8FF", width=2.8, shape="spline", smoothing=0.45),
                marker=dict(size=6, color="#37E8FF"),
            )
        )

        fig.update_layout(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=10, r=10, t=10, b=10),
            xaxis=dict(
                showgrid=True,
                gridcolor="rgba(255,255,255,0.06)",
                tickfont=dict(color="#A7ADBA", size=10),
                linecolor="rgba(255,255,255,0.1)",
            ),
            yaxis=dict(
                showgrid=True,
                gridcolor="rgba(255,255,255,0.06)",
                tickfont=dict(color="#A7ADBA", size=10),
                linecolor="rgba(255,255,255,0.1)",
                ticksuffix="%",
            ),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1,
                font=dict(color="#F5F7FA", size=11),
            ),
            hovermode="x unified",
        )

        with st.container(border=True):
            st.markdown('<div class="chart-title"><span>累计净值收益率曲线</span><span class="pill pill-cyan">回测模拟</span></div>', unsafe_allow_html=True)
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False, "responsive": True})

        # Step-by-Step transaction data logs
        render_section_title("每日交易流水", "回测期间组合每日持仓变动与资产明细")
        
        view_df = df_vals.copy()
        view_df["Date"] = view_df["Date"].dt.strftime("%Y-%m-%d")
        view_df = view_df.rename(
            columns={
                "Date": "日期",
                "Portfolio Value": "组合总值",
                "Portfolio Return": "累计回报",
                "Long Exposure": "多头敞口",
                "Short Exposure": "空头敞口",
                "Net Exposure": "净敞口",
            }
        )
        
        # Formatting
        view_df["组合总值"] = view_df["组合总值"].map(lambda x: f"${x:,.2f}")
        view_df["累计回报"] = view_df["累计回报"].map(lambda x: f"{x:+.2f}%")
        for col in ["多头敞口", "空头敞口", "净敞口"]:
            if col in view_df.columns:
                view_df[col] = pd.to_numeric(view_df[col], errors="coerce").map(lambda x: f"{x * 100:.1f}%" if not pd.isna(x) else "-")

        keep_cols = ["日期", "组合总值", "累计回报", "多头敞口", "空头敞口", "净敞口"]
        view_df = view_df[[c for c in keep_cols if c in view_df.columns]]
        
        render_glass_dataframe(view_df.head(100), height=520)


def render_hedge_dashboard() -> None:
    # 1. Parameter Command Bar
    with st.container(border=True):
        st.markdown('<div class="command-bar-title">量化对冲参数与策略</div>', unsafe_allow_html=True)
        command_cols = st.columns([0.76, 0.24], vertical_alignment="top")
        
        with command_cols[0]:
            inner_cols = st.columns(2)
            with inner_cols[0]:
                st.markdown('<div class="command-field-label">股票代码 / 名称</div>', unsafe_allow_html=True)
                tickers_input = st.text_input(
                    "股票代码 / 名称",
                    value="",
                    placeholder="输入 600519、贵州茅台、300750 等代码或名称",
                    key="hedge_tickers",
                    label_visibility="collapsed"
                )
                
                # Resolve stock names and matching
                resolved_stocks = []
                unmatched_tokens = []
                try:
                    directory = get_stock_directory_cache()
                    tokens = [t.strip() for t in tickers_input.split(",") if t.strip()]
                    
                    for token in tokens:
                        matches = resolve_stock_query(token, directory, limit=1)
                        if matches:
                            resolved_stocks.append(matches[0])
                        else:
                            unmatched_tokens.append(token)
                    
                    if resolved_stocks:
                        matched_str = ", ".join([f"{s['name']} ({s['code']})" for s in resolved_stocks])
                        st.caption(f"已匹配：{matched_str}")
                    if unmatched_tokens:
                        unmatched_str = ", ".join(unmatched_tokens)
                        st.warning(f"未匹配：{unmatched_str}")
                except Exception as ex:
                    logger.warning("Failed to resolve stock query in hedge UI: %s", ex)
            
            with inner_cols[1]:
                st.markdown('<div class="command-field-label">运行模式</div>', unsafe_allow_html=True)
                mode = st.segmented_control(
                    "运行模式",
                    ["单日决策", "回测模拟"],
                    default="单日决策",
                    key="hedge_mode",
                    label_visibility="collapsed"
                )
            
            # Additional parameters (domestic trading hour aware default dates)
            _now = pd.Timestamp.now(tz="Asia/Shanghai").tz_localize(None)
            if _now.dayofweek < 5 and _now.hour >= 16:
                default_end = _now.normalize().date()
            else:
                default_end = (_now.normalize() - pd.offsets.BDay(1)).date()
            
            default_start = (pd.Timestamp(default_end) - pd.offsets.BDay(60)).date()

            if mode == "回测模拟":
                extra_cols = st.columns(3)
                with extra_cols[0]:
                    st.markdown('<div class="command-field-label">开始日期</div>', unsafe_allow_html=True)
                    start_date = st.date_input(
                        "hedge_start",
                        value=default_start,
                        key="hedge_start_date",
                        label_visibility="collapsed"
                    )
                with extra_cols[1]:
                    st.markdown('<div class="command-field-label">结束日期</div>', unsafe_allow_html=True)
                    end_date = st.date_input(
                        "hedge_end",
                        value=default_end,
                        key="hedge_end_date",
                        label_visibility="collapsed"
                    )
                with extra_cols[2]:
                    st.markdown('<div class="command-field-label">初始资金</div>', unsafe_allow_html=True)
                    initial_cash = st.number_input(
                        "hedge_cash",
                        min_value=1000,
                        value=100000,
                        step=10000,
                        format="%d",
                        key="hedge_initial_cash",
                        label_visibility="collapsed"
                    )
            else:
                extra_cols = st.columns(2)
                with extra_cols[0]:
                    st.markdown('<div class="command-field-label">开始日期</div>', unsafe_allow_html=True)
                    start_date = st.date_input(
                        "hedge_start",
                        value=default_start,
                        key="hedge_start_date",
                        label_visibility="collapsed"
                    )
                with extra_cols[1]:
                    st.markdown('<div class="command-field-label">分析日期</div>', unsafe_allow_html=True)
                    end_date = st.date_input(
                        "hedge_end",
                        value=default_end,
                        key="hedge_end_date",
                        label_visibility="collapsed"
                    )
                initial_cash = 100000.0


            # Analyst Multiselect replaced by Jocket expander + skill buttons container
            st.markdown('<div class="command-field-label">参与决策的智能体</div>', unsafe_allow_html=True)
            if "selected_hedge_agents" not in st.session_state:
                st.session_state["selected_hedge_agents"] = []
            selected_agent_keys = st.session_state["selected_hedge_agents"]
            
            # Display active selection above the expander capsule
            agent_map = {a["key"]: a["display_name"] for a in get_agents_list()}
            selected_names = [agent_map[k] for k in selected_agent_keys if k in agent_map]
            if selected_names:
                st.caption(f"当前选择：{', '.join(selected_names)}")
            else:
                st.caption("当前选择：无（请在下方展开选择参与决策的智能体）")
            
            def toggle_hedge_agent(agent_key):
                agents = set(st.session_state.get("selected_hedge_agents", []))
                if agent_key in agents:
                    agents.remove(agent_key)
                else:
                    agents.add(agent_key)
                st.session_state["selected_hedge_agents"] = list(agents)

            with st.expander("选择参与决策的智能体", expanded=False):
                st.markdown('<div class="ai-skill-buttons-container" style="display:none"></div>', unsafe_allow_html=True)
                
                for agent in get_agents_list():
                    agent_key = agent["key"]
                    display_name = agent["display_name"]
                    st.button(
                        display_name,
                        key=f"ai_skill_{agent_key}",
                        help=agent["description"],
                        type="primary" if agent_key in selected_agent_keys else "secondary",
                        use_container_width=False,
                        on_click=toggle_hedge_agent,
                        args=(agent_key,)
                    )

        with command_cols[1]:
            st.markdown('<div class="command-field-label spacer">&nbsp;</div>', unsafe_allow_html=True)
            tracker = st.session_state.get("hedge_tracker")
            is_busy = tracker is not None and tracker.is_running
            
            if st.button("来财来财", type="primary", use_container_width=True, disabled=is_busy, key="run_hedge_analysis"):
                parsed_tickers = [s["code"] for s in resolved_stocks] if resolved_stocks else [t.strip().upper() for t in tickers_input.split(",") if t.strip()]
                if not parsed_tickers:
                    st.error("❌ 请输入至少一个股票代码")
                elif not selected_agent_keys:
                    st.error("❌ 请选择至少一个AI分析师")
                else:
                    # Construct initial portfolio
                    portfolio = {
                        "cash": float(initial_cash),
                        "margin_requirement": 1.0,
                        "positions": {
                            ticker: {
                                "long": 0,
                                "short": 0,
                                "long_cost_basis": 0.0,
                                "short_cost_basis": 0.0,
                                "short_margin_used": 0.0,
                            }
                            for ticker in parsed_tickers
                        },
                        "realized_gains": {
                            ticker: {
                                "long": 0.0,
                                "short": 0.0,
                            }
                            for ticker in parsed_tickers
                        },
                    }
                    
                    # Initialize progress tracker
                    tracker = HedgeProgressTracker(parsed_tickers, mode)
                    st.session_state["hedge_tracker"] = tracker
                    
                    # Launch analysis in daemon thread
                    t = threading.Thread(
                        target=run_hedge_in_thread,
                        args=(
                            parsed_tickers,
                            start_date.strftime("%Y-%m-%d"),
                            end_date.strftime("%Y-%m-%d"),
                            portfolio,
                            selected_agent_keys,
                            mode,
                            tracker,
                        ),
                        daemon=True
                    )
                    t.start()
                    st.rerun()


    # 2. Rendering state machine logic
    tracker = st.session_state.get("hedge_tracker")
    if tracker:
        tracker.update_elapsed()
        
        if tracker.is_running:
            render_hedge_progress(tracker)
            time.sleep(1.8)
            st.rerun()
            
        elif tracker.error:
            st.error(f"❌ 运行失败: {tracker.error}")
            if st.button("重试", type="primary"):
                st.session_state.pop("hedge_tracker", None)
                st.rerun()
                
        elif tracker.is_complete:
            if tracker.mode == "单日决策":
                render_single_day_report(tracker.final_result, tracker.tickers)
            else:
                render_backtest_report(tracker)
    else:
        # Initial visual landing
        render_hero(
            code="AI多智能体对冲",
            data_source="自动更新",
            latest_date="-",
            updated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
            title="22 位量化对冲智能体群就绪",
            subtitle="在上方配置投资组合与历史周期，启动 LangGraph 协同式量化对冲决策与回测。系统会自动运行：数据门控 → 多元投研 → 仓位管理 → 压力测试 → 组合优化。",
            ai_summary=None
        )
