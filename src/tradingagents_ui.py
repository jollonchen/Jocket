import sys
import os
import time
from pathlib import Path
from datetime import date
from html import escape

import streamlit as st

# Add tradingagents_src to sys.path so its internal imports work naturally
_TA_SRC = os.path.join(os.path.dirname(__file__), "tradingagents_src")
if _TA_SRC not in sys.path:
    sys.path.insert(0, _TA_SRC)

from web.progress import ProgressTracker
from web.runner import run_analysis_in_thread
from web.history import get_history, load_analysis, extract_signal
from tradingagents.default_config import DEFAULT_CONFIG
from src.ui_components import render_section_title, render_bento_grid, metric_card, render_glass_dataframe, render_hero
from web.pdf_export import generate_pdf
from datetime import datetime
import functools

def _build_ta_config() -> dict:
    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = "deepseek"
    config["deep_think_llm"] = "deepseek-v4-pro"
    config["quick_think_llm"] = "deepseek-v4-flash"
    config["data_vendors"] = {
        "core_stock_apis": "a_stock",
        "technical_indicators": "a_stock",
        "fundamental_data": "a_stock",
        "news_data": "a_stock",
        "signal_data": "a_stock",
    }
    config["max_debate_rounds"] = 1
    config["max_risk_discuss_rounds"] = 1
    config["output_language"] = "Chinese"
    return config

def _strip_think(text: str) -> str:
    import re
    return re.sub(r"<think>.*?</think>\s*", "", str(text), flags=re.DOTALL).strip()

def _infer_debate_result(state: dict, signal: str) -> tuple[str, str]:
    import re

    debate = state.get("investment_debate_state")
    judge_text = ""
    if isinstance(debate, dict):
        judge_text = _strip_think(debate.get("judge_decision", "") or "")

    text = judge_text.replace(" ", "")
    bull_hits = [
        "多方胜", "多方胜利", "多方获胜", "多方占优", "多方压倒", "多方逻辑更强",
        "牛方胜", "Bull胜", "Bull胜利", "BullAnalyst胜",
    ]
    bear_hits = [
        "空方胜", "空方胜利", "空方获胜", "空方占优", "空方压倒", "空方逻辑更强",
        "熊方胜", "Bear胜", "Bear胜利", "BearAnalyst胜",
    ]
    draw_hits = ["平手", "打平", "势均力敌", "双方均", "多空均衡", "维持中性", "中性结论"]

    if any(hit in text for hit in draw_hits):
        return "draw", "cyan"
    if re.search(r"(多方|Bull|牛方).{0,30}(压倒|胜过|优于|强于).{0,30}(空方|Bear|熊方)", text):
        return "bull_win", "green"
    if re.search(r"(空方|Bear|熊方).{0,30}(压倒|胜过|优于|强于).{0,30}(多方|Bull|牛方)", text):
        return "bear_win", "red"
    if any(hit in text for hit in bull_hits):
        return "bull_win", "green"
    if any(hit in text for hit in bear_hits):
        return "bear_win", "red"

    s_upper = str(signal or "").upper()
    if any(word in s_upper for word in ("BUY", "OVERWEIGHT")):
        return "bull_win", "green"
    if any(word in s_upper for word in ("SELL", "UNDERWEIGHT")):
        return "bear_win", "red"
    return "draw", "cyan"

@functools.lru_cache(maxsize=1)
def _stock_name_map() -> dict[str, str]:
    """Build a fast code→name lookup dictionary (called once, cached forever)."""
    from src.stock_lookup import build_stock_directory
    try:
        directory = build_stock_directory()
        name_map: dict[str, str] = {}
        for _, row in directory.iterrows():
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            for col in ("code", "display_code"):
                c = str(row.get(col) or "").strip()
                if c:
                    name_map[c] = name
        return name_map
    except Exception:
        return {}

def _resolve_stock_name(code: str) -> str:
    """Resolve a stock code to its Chinese name via fast dict lookup."""
    return _stock_name_map().get(str(code).strip(), "")

@st.dialog("确认删除投研报告")
def confirm_delete_dialog(entry):
    t, d, path = entry["ticker"], entry["date"], entry["path"]
    name = entry.get("company_name") or _resolve_stock_name(t)
    display_name = f"{name}（{t}）" if name else t
    
    st.markdown(
        f"""
        <div style="text-align: center; margin: 0 0 12px; font-family: Inter, -apple-system, sans-serif;">
            <p class="dialog-sub-text" style="font-size: 13px !important; font-weight: 300 !important; color: rgba(255, 255, 255, 0.6) !important; margin: 0 0 10px; line-height: 1.4;">您确定要永久删除该投研报告吗？</p>
            <div style="background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 16px; padding: 10px; margin: 10px 0;">
                <p class="dialog-stock-name" style="font-size: 13px !important; font-weight: 400 !important; color: rgba(255, 255, 255, 0.9) !important; margin: 0 0 4px; letter-spacing: 0.3px;">{display_name}</p>
                <p class="dialog-report-date" style="font-size: 11px !important; font-weight: 300 !important; color: rgba(255, 255, 255, 0.4) !important; margin: 0;">报告日期：{d}</p>
            </div>
            <p class="dialog-warning-text" style="font-size: 11px !important; font-weight: 300 !important; color: rgba(255, 255, 255, 0.35) !important; margin: 8px 0 0; line-height: 1.4;">注意：此操作不仅会从页面移除，还将永久删除本地的 JSON 文件。</p>
        </div>
        """,
        unsafe_allow_html=True
    )
    
    cols = st.columns(2)
    with cols[0]:
        if st.button("取消", key="cancel_del_btn", use_container_width=True):
            st.rerun()
    with cols[1]:
        if st.button("确认删除", key="confirm_del_btn", type="primary", use_container_width=True):
            import os
            try:
                p = Path(path)
                if p.exists():
                    p.unlink()
                    # Invalidate the history cache so next get_history() re-scans
                    from web.history import _history_cache
                    _history_cache["key"] = ""
                    _history_cache["data"] = []
                    st.markdown(
                        """
                        <div class="delete-success-alert">
                            <span style="color: #37E8FF; font-weight: 900; margin-right: 4px;">✓</span> 已成功删除报告及本地文件
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                    
                    # Clean up empty parent directories up to logs dir
                    parent_dir = p.parent
                    if parent_dir.exists() and not os.listdir(parent_dir):
                        parent_dir.rmdir()
                        ticker_dir = parent_dir.parent
                        if ticker_dir.exists() and not os.listdir(ticker_dir):
                            ticker_dir.rmdir()
                    
                    # If this is the active report, clear it
                    if st.session_state.get("ta_viewing_history") == path:
                        st.session_state["ta_viewing_history"] = None
                else:
                    st.error("文件不存在，可能已被手动删除。")
            except Exception as e:
                st.error(f"删除失败: {e}")
            time.sleep(2.5)
            st.rerun()

def render_jocket_report(state: dict, ticker: str, trade_date: str, signal: str, elapsed: float | None = None, stock_name: str = "") -> None:
    # Top Signal Hero (Using Jocket Bento Grid)
    signal_tone = "blue"
    indicator = "neutral"
    s_upper = signal.upper()
    if "BUY" in s_upper:
        signal_tone = "green"
        indicator = "strong"
    elif "OVERWEIGHT" in s_upper:
        signal_tone = "cyan"
        indicator = "mild_strong"
    elif "HOLD" in s_upper:
        signal_tone = "orange"
        indicator = "neutral"
    elif "UNDERWEIGHT" in s_upper:
        signal_tone = "purple"
        indicator = "mild_weak"
    elif "SELL" in s_upper:
        signal_tone = "red"
        indicator = "weak"

    if not stock_name:
        stock_name = _resolve_stock_name(ticker)
    display_ticker = f"{stock_name}（{ticker}）" if stock_name else ticker

    time_note = f"耗时 {int(elapsed)//60}:{int(elapsed)%60:02d}" if elapsed else "历史报告"
    debate_indicator, debate_tone = _infer_debate_result(state, signal)
    col_left, col_right = st.columns([2.0, 0.45], vertical_alignment="center")
    
    with col_left:
        cards = [
            metric_card("最终决策信号", signal.upper(), f"报告日期：{trade_date}", signal_tone, indicator),
            metric_card("分析对象", display_ticker, time_note, debate_tone, debate_indicator),
        ]
        render_bento_grid(cards)

    pdf_bytes = None
    try:
        pdf_bytes = generate_pdf(state, ticker, trade_date, signal)
    except Exception:
        pass

    with col_right:
        if pdf_bytes:
            st.download_button(
                "下载PDF报告",
                data=pdf_bytes,
                file_name=f"Jocket_TradingAgents_{ticker}_{trade_date}.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True,
                key="ta_download_pdf_btn"
            )
        else:
            st.button("下载PDF报告", disabled=True, use_container_width=True, key="ta_download_pdf_btn", type="primary")
            
        st.markdown('<div style="height: 10px;"></div>', unsafe_allow_html=True)
        
        if st.button("返回首页", key="ta_back_home_btn", type="primary", use_container_width=True):
            st.session_state["ta_viewing_history"] = None
            st.session_state["ta_tracker"] = None
            st.rerun()

    inv_plan = state.get("investment_plan", "")
    if inv_plan:
        render_section_title("最终投资建议", "综合多方分析、辩论与风控的最终策略")
        with st.container(border=False):
            st.markdown(_strip_think(inv_plan))

    render_section_title("多维分析师报告", "独立 AI 智能体生成的研究视图")
    
    sections = [
        ("market_report", "技术分析"),
        ("sentiment_report", "市场情绪"),
        ("news_report", "新闻舆情"),
        ("fundamentals_report", "基本面"),
        ("policy_report", "政策分析"),
        ("hot_money_report", "游资追踪"),
        ("lockup_report", "解禁减持"),
    ]

    for key, title in sections:
        content = state.get(key, "")
        if content:
            with st.expander(f"📊 {title}"):
                st.markdown(_strip_think(content))

    debate = state.get("investment_debate_state")
    if debate and isinstance(debate, dict):
        render_section_title("多空辩论", "多方与空方 AI 投研总监的深度交锋")
        with st.container(border=False):
            t1, t2, t3 = st.tabs(["多方观点", "空方观点", "研究经理裁决"])
            with t1:
                st.markdown(_strip_think(debate.get("bull_history", "") or "无数据"))
            with t2:
                st.markdown(_strip_think(debate.get("bear_history", "") or "无数据"))
            with t3:
                st.markdown(_strip_think(debate.get("judge_decision", "") or "无数据"))

    risk = state.get("risk_debate_state")
    if risk and isinstance(risk, dict):
        render_section_title("风控评估", "对当前交易计划的压力测试与风险暴露分析")
        with st.container(border=False):
            t1, t2, t3, t4 = st.tabs(["激进策略", "保守策略", "中性策略", "风控决策"])
            with t1:
                st.markdown(_strip_think(risk.get("aggressive_history", "") or "无数据"))
            with t2:
                st.markdown(_strip_think(risk.get("conservative_history", "") or "无数据"))
            with t3:
                st.markdown(_strip_think(risk.get("neutral_history", "") or "无数据"))
            with t4:
                st.markdown(_strip_think(risk.get("judge_decision", "") or "无数据"))

    dqs = state.get("data_quality_summary", "")
    if dqs:
        with st.expander("✅ 数据质量摘要"):
            st.markdown(str(dqs))


def render_jocket_progress_details(tracker: ProgressTracker) -> None:
    from web.progress import PIPELINE_STAGES

    # Stats Cards
    metrics_html = f"""
    <div class="ta-stats-container">
        <div class="ta-stat-card" style="--card-color: #FF5C7A;">
            <div class="ta-stat-title">LLM 调用</div>
            <div class="ta-stat-value">{tracker.llm_calls}</div>
        </div>
        <div class="ta-stat-card" style="--card-color: #FFB86B;">
            <div class="ta-stat-title">工具调用</div>
            <div class="ta-stat-value">{tracker.tool_calls}</div>
        </div>
        <div class="ta-stat-card" style="--card-color: #37E8FF;">
            <div class="ta-stat-title">输入 Tokens</div>
            <div class="ta-stat-value">{tracker.tokens_in:,}</div>
        </div>
        <div class="ta-stat-card" style="--card-color: #9B5CFF;">
            <div class="ta-stat-title">输出 Tokens</div>
            <div class="ta-stat-value">{tracker.tokens_out:,}</div>
        </div>
    </div>
    """
    st.markdown(metrics_html, unsafe_allow_html=True)
 
    if tracker.error:
        st.error(f"错误: {tracker.error}")
 
    completed_reports = [
        (stage["name"], stage["icon"], tracker.stage_reports[stage["id"]])
        for stage in PIPELINE_STAGES
        if stage["id"] in tracker.stage_reports
    ]
 
    if completed_reports:
        for name, icon, report in reversed(completed_reports):
            is_latest = (name == completed_reports[-1][0])
            with st.expander(f"{icon} {name}", expanded=is_latest):
                st.markdown(_strip_think(report[:3000]))

def render_tradingagents_dashboard() -> None:
    # Check if delete modal is triggered
    if "ta_delete_target" in st.session_state and st.session_state["ta_delete_target"]:
        target = st.session_state.pop("ta_delete_target")
        confirm_delete_dialog(target)

    # 1. Command Bar
    with st.container(border=False):
        st.markdown('<div class="jocket-bottom-dock style-bottom" data-jocket-dock-style="style bottom"></div>', unsafe_allow_html=True)
        command_cols = st.columns([0.76, 0.24], vertical_alignment="center")
        
        with command_cols[0]:
            inner_cols = st.columns(2)
            with inner_cols[0]:
                st.markdown('<div class="command-field-label">股票名称/代码</div>', unsafe_allow_html=True)
                ticker = st.text_input(
                    "ticker",
                    placeholder="例如: 300750",
                    key="ta_input_ticker",
                    label_visibility="collapsed"
                )
                
                from src.stock_lookup import resolve_stock_query, build_stock_directory
                resolved_code = ticker.strip()
                resolved_name = ticker.strip()
                matched_msg = ""
                unmatched_msg = ""
                if resolved_code:
                    matches = resolve_stock_query(resolved_code, build_stock_directory())
                    if matches:
                        selected = matches[0]
                        resolved_code = str(selected.get("code") or "")
                        resolved_name = str(selected.get("name") or "")
                        matched_msg = f"已匹配：{resolved_name}（{resolved_code}）"
                    else:
                        unmatched_msg = "没有匹配到股票。可以尝试输入代码或更短的名称关键词。"
            
            with inner_cols[1]:
                st.markdown('<div class="command-field-label">选择日期</div>', unsafe_allow_html=True)
                trade_date = st.date_input(
                    "date",
                    value=date.today(),
                    key="ta_input_date",
                    label_visibility="collapsed"
                )
            
        with command_cols[1]:
            st.markdown('<div class="command-field-label spacer">&nbsp;</div>', unsafe_allow_html=True)
            tracker = st.session_state.get("ta_tracker")
            is_busy = tracker is not None and tracker.is_running
            if st.button("来财来财", type="primary", use_container_width=True, disabled=is_busy, key="run_ta_analysis"):
                if not ticker.strip():
                    st.error("❌ 请输入股票代码或名称")
                elif not resolved_code:
                    st.error("❌ 未匹配到有效股票，请检查输入")
                else:
                    # Resolve to Yahoo format if needed, but tradingagents typically uses standard formats.
                    # We pass the pure code here (e.g. 002050)
                    st.session_state["ta_start_analysis"] = {
                        "ticker": resolved_code,
                        "trade_date": trade_date.strftime("%Y-%m-%d"),
                        "company_name": resolved_name,
                    }
                    st.session_state["ta_viewing_history"] = None



    # Render matching messages outside the floating dock
    from html import escape
    if ticker.strip():
        if matched_msg:
            st.markdown(f'<div class="dock-matching-msg matched">{escape(matched_msg)}</div>', unsafe_allow_html=True)
        elif unmatched_msg:
            st.markdown(f'<div class="dock-matching-msg unmatched">{escape(unmatched_msg)}</div>', unsafe_allow_html=True)

    # State Machine Logic
    start_req = st.session_state.pop("ta_start_analysis", None)
    if start_req:
        tracker = ProgressTracker(
            ticker=start_req["ticker"],
            trade_date=start_req["trade_date"],
        )
        st.session_state["ta_tracker"] = tracker
        run_analysis_in_thread(
            ticker=start_req["ticker"],
            trade_date=start_req["trade_date"],
            config=_build_ta_config(),
            tracker=tracker,
            company_name=start_req.get("company_name", ""),
        )
        st.rerun()

    tracker = st.session_state.get("ta_tracker")
    viewing_history = st.session_state.get("ta_viewing_history")

    if viewing_history:
        try:
            state = load_analysis(viewing_history)
            signal = extract_signal(state)
            ticker = Path(viewing_history).parent.parent.name
            trade_date = Path(viewing_history).stem.replace("full_states_log_", "")
            
            # Prefer the name saved directly in the report, or extract from text reports, or fall back to map
            from web.history import parse_company_name_from_json
            stock_name = state.get("company_name") or parse_company_name_from_json(Path(viewing_history), ticker, state) or _resolve_stock_name(ticker)
            
            render_jocket_report(state, ticker, trade_date, signal, stock_name=stock_name)
        except Exception as exc:
            st.error(f"加载失败: {exc}")

    elif tracker and tracker.is_running:
        from src.ui_components import render_jocket_unified_empty_state
        with st.container(key="jocket_page_g_landing"):
            render_jocket_unified_empty_state(
                "投研分析",
                "",
                [],
                show_progress_key="ta_tracker"
            )
        time.sleep(2)
        st.rerun()

    elif tracker and tracker.is_complete:
        # Resolve company name for complete tracker
        from web.history import parse_company_name_from_json
        stock_name = tracker.final_state.get("company_name") or parse_company_name_from_json(None, tracker.ticker, tracker.final_state) or getattr(tracker, "company_name", "") or _resolve_stock_name(tracker.ticker)
        render_jocket_report(
            tracker.final_state,
            tracker.ticker,
            tracker.trade_date,
            tracker.signal,
            elapsed=tracker.elapsed,
            stock_name=stock_name,
        )

    elif tracker and tracker.error:
        st.error(f"分析失败: {tracker.error}")
        if st.button("重试", type="primary"):
            st.session_state.pop("ta_tracker", None)
            st.rerun()

    else:
        from src.ui_components import render_jocket_unified_empty_state
        with st.container(key="jocket_page_g_landing"):
            render_jocket_unified_empty_state(
                "投研分析",
                "多智能体群组分析及生成高质量投研报告，点击按钮或输入后运行",
                []
            )
            
            # Center history selector dropdown (replacing the previous 4 button position)
            history = get_history()
            if history:
                with st.container(key="ta_history_style_expander"):
                    with st.popover("历史报告", use_container_width=True):
                        st.markdown(
                            """
                            <link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1" rel="stylesheet" />
                            <div class="flex items-center justify-between" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                                <h2 style="font-size: 14px; font-weight: 600; color: #e1e2eb; margin: 0;">选择历史报告</h2>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )
                        
                        for idx, entry in enumerate(history[:12]):
                            t, d = entry["ticker"], entry["date"]
                            name = entry.get("company_name") or _resolve_stock_name(t)
                            
                            # Premium markdown label format for Streamlit 1.45.1 button
                            markdown_label = f"**{name}**\n\n`{t}`   {d}" if name else f"**{t}**\n\n`{t}`   {d}"
                            
                            col_btn, col_del = st.columns([0.85, 0.15], vertical_alignment="center", gap="small")
                            with col_btn:
                                if st.button(markdown_label, key=f"ta_hist_select_{idx}", use_container_width=True):
                                    st.session_state["ta_viewing_history"] = entry["path"]
                                    st.session_state["ta_start_analysis"] = None
                                    st.rerun()
                            with col_del:
                                if st.button("✕", key=f"ta_del_select_{idx}", use_container_width=True):
                                    st.session_state["ta_delete_target"] = entry
                                    st.rerun()
