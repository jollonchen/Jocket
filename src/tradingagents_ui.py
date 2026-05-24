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
        <div style="text-align: center; margin: 5px 0 15px;">
            <p class="dialog-sub-text" style="font-size: 0.85rem !important; color: #A7ADBA; margin-bottom: 10px; line-height: 1.4;">您确定要永久删除该投研报告吗？</p>
            <div style="background: rgba(255, 92, 122, 0.06); border: 1px solid rgba(255, 92, 122, 0.2); border-radius: 20px; padding: 12px; margin: 12px 0;">
                <p class="dialog-stock-name" style="font-size: 1.05rem !important; font-weight: 800; color: #FF5C7A; margin: 0 0 4px;">{display_name}</p>
                <p class="dialog-report-date" style="font-size: 0.8rem !important; color: #A7ADBA; margin: 0;">报告日期：{d}</p>
            </div>
            <p class="dialog-warning-text" style="font-size: 0.76rem !important; color: #FFB86B; margin-top: 10px; opacity: 0.95; line-height: 1.45;">注意：此操作不仅会从页面移除，还将永久删除本地的 JSON 文件。</p>
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
    cards = [
        metric_card("最终决策信号", signal.upper(), f"报告日期：{trade_date}", signal_tone, indicator),
        metric_card("分析对象", display_ticker, time_note, debate_tone, debate_indicator),
    ]
    render_bento_grid(cards)

    try:
        pdf_bytes = generate_pdf(state, ticker, trade_date, signal)
        st.download_button(
            "📥 下载专业 PDF 报告",
            data=pdf_bytes,
            file_name=f"Jocket_TradingAgents_{ticker}_{trade_date}.pdf",
            mime="application/pdf",
            type="primary",
            use_container_width=True
        )
    except Exception as e:
        pass

    inv_plan = state.get("investment_plan", "")
    if inv_plan:
        render_section_title("最终投资建议", "综合多方分析、辩论与风控的最终策略")
        with st.container(border=True):
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
        with st.container(border=True):
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
        with st.container(border=True):
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


def _status_badge(status: str) -> str:
    if status == "done":
        return '<span style="color:#33D69F; font-size:1.4rem;">●</span>'
    if status == "active":
        return '<span style="color:#FFB86B; font-size:1.4rem; text-shadow: 0 0 8px rgba(255,184,107,0.6);">◉</span>'
    return '<span style="color:#A7ADBA; font-size:1.4rem; opacity: 0.3;">○</span>'

def _format_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"

def render_jocket_progress(tracker: ProgressTracker) -> None:
    from web.progress import PIPELINE_STAGES
    
    completed = len(tracker.completed_stages)
    total = len(PIPELINE_STAGES)
    pct = completed / total if total else 0
    
    # Base Styles
    st.markdown(
        f"""
        <style>
        .ta-progress-wrapper {{
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 16px;
            padding: 24px;
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            margin: 1rem 0 2rem;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05), 0 8px 32px rgba(0, 0, 0, 0.2);
        }}
        .ta-progress-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 24px;
            padding-bottom: 16px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            font-size: 0.9rem;
            color: #A7ADBA;
            letter-spacing: 0.5px;
        }}
        .ta-progress-header strong {{
            color: #fff;
            font-weight: 600;
        }}
        .ta-progress-container {{
            position: relative;
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            width: 100%;
            padding-top: 10px;
        }}
        .ta-progress-track {{
            position: absolute;
            top: 21px; /* 10px padding + 12px half icon height */
            left: 30px;
            right: 30px;
            height: 4px;
            background: rgba(255, 255, 255, 0.08);
            border-radius: 2px;
            z-index: 0;
        }}
        .ta-progress-fill {{
            position: absolute;
            top: 0;
            left: 0;
            height: 100%;
            background: linear-gradient(90deg, #33D69F, #37E8FF, #33D69F);
            background-size: 200% 100%;
            animation: flowLight 1.5s linear infinite;
            border-radius: 2px;
            box-shadow: 0 0 10px rgba(55, 232, 255, 0.5);
            transition: width 0.5s ease-out;
            z-index: 1;
        }}
        .ta-stage-item {{
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 12px;
            transition: all 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
            width: 60px;
            z-index: 2; /* Above the track */
        }}
        .ta-stage-item.pending {{ opacity: 0.4; transform: scale(0.95); }}
        .ta-stage-item.active {{ opacity: 1; transform: scale(1.15) translateY(-4px); z-index: 10; }}
        .ta-stage-item.done {{ opacity: 1; transform: scale(1); }}
        
        .ta-stage-icon {{
            width: 24px; height: 24px;
            border-radius: 50%;
            position: relative;
            background: rgba(255, 255, 255, 0.08);
            border: 2px solid rgba(255, 255, 255, 0.15);
            transition: all 0.3s ease;
        }}
        .ta-stage-icon.active {{
            background: rgba(55, 232, 255, 1);
            border: 2px solid rgba(55, 232, 255, 0.8);
            box-shadow: 0 0 12px rgba(55, 232, 255, 0.6);
            animation: pulseGlow 2s infinite ease-in-out;
        }}
        .ta-stage-icon.done {{
            background: rgba(51, 214, 159, 1);
            border: 2px solid rgba(51, 214, 159, 0.8);
            box-shadow: 0 0 8px rgba(51, 214, 159, 0.4);
        }}
        @keyframes pulseGlow {{
            0% {{ box-shadow: 0 0 8px rgba(55, 232, 255, 0.4); }}
            50% {{ box-shadow: 0 0 16px rgba(55, 232, 255, 0.8); }}
            100% {{ box-shadow: 0 0 8px rgba(55, 232, 255, 0.4); }}
        }}
        .ta-stage-label {{ font-size: 0.75rem; letter-spacing: 0.5px; white-space: nowrap; }}
        .ta-stage-label.pending {{ color: #A7ADBA; }}
        .ta-stage-label.active {{ color: #fff; font-weight: 700; text-shadow: 0 0 8px rgba(255,255,255,0.6); }}
        .ta-stage-label.done {{ color: #33D69F; }}
        
        @keyframes flowLight {{
            0% {{ background-position: 100% 0; }}
            100% {{ background-position: -100% 0; }}
        }}
        
        .ta-stats-container {{
            display: flex; gap: 16px; margin: 2rem 0; width: 100%;
        }}
        .ta-stat-card {{
            flex: 1;
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 16px;
            padding: 16px 20px;
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.1), 0 8px 24px rgba(0, 0, 0, 0.2);
            transition: all 0.3s ease;
            position: relative; overflow: hidden;
        }}
        .ta-stat-card:hover {{
            transform: translateY(-3px);
            background: rgba(255, 255, 255, 0.06);
            border-color: rgba(255, 255, 255, 0.18);
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2), 0 12px 32px rgba(0, 0, 0, 0.3);
        }}
        .ta-stat-card::before {{
            content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px;
            background: linear-gradient(90deg, var(--card-color), transparent); opacity: 0.7;
        }}
        .ta-stat-title {{ color: var(--card-color); font-size: 0.9rem; font-weight: 600; letter-spacing: 0.5px; margin-bottom: 8px; display: flex; align-items: center; gap: 6px; }}
        .ta-stat-value {{ font-size: 2.2rem; font-weight: 700; color: var(--card-color); text-shadow: 0 2px 10px rgba(0,0,0,0.3); font-family: 'Inter', -apple-system, sans-serif; line-height: 1.1; }}
        </style>
        """, unsafe_allow_html=True
    )
    
    # Remove st.progress completely to avoid default UI flashing
    
    # Generate HTML for stages
    mins = int(tracker.elapsed // 60)
    secs = int(tracker.elapsed % 60)
    
    # Calculate the fill percentage for the track
    fill_pct = 0
    if total > 1:
        fill_pct = (completed / (total - 1)) * 100
        
    stages_html = ""
    stages_html += '<div class="ta-progress-wrapper">\n'
    stages_html += '  <div class="ta-progress-header">\n'
    stages_html += f'    <div>分析进度：<strong>{completed}/{total}</strong> 阶段完成</div>\n'
    stages_html += f'    <div>耗时：<strong>{mins}分{secs:02d}秒</strong></div>\n'
    stages_html += '  </div>\n'
    stages_html += '  <div class="ta-progress-container">\n'
    stages_html += '    <div class="ta-progress-track">\n'
    stages_html += f'      <div class="ta-progress-fill" style="width: {fill_pct}%;"></div>\n'
    stages_html += '    </div>\n'
    
    for i, stage in enumerate(PIPELINE_STAGES):
        status = tracker.stage_status(stage["id"])
        
        stages_html += f'    <div class="ta-stage-item {status}">\n'
        stages_html += f'      <div class="ta-stage-icon {status}"></div>\n'
        stages_html += f'      <div class="ta-stage-label {status}">{stage["name"]}</div>\n'
        stages_html += '    </div>\n'
        
    stages_html += '  </div>\n'
    stages_html += '</div>\n'
    
    st.markdown(stages_html, unsafe_allow_html=True)

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
    with st.container(border=True):
        st.markdown('<div class="command-bar-title">参数与操作</div>', unsafe_allow_html=True)
        command_cols = st.columns([0.76, 0.24], vertical_alignment="top")
        
        with command_cols[0]:
            inner_cols = st.columns(2)
            with inner_cols[0]:
                st.markdown('<div class="command-field-label">股票代码 / 名称</div>', unsafe_allow_html=True)
                ticker = st.text_input(
                    "ticker",
                    placeholder="例如: 300750",
                    key="ta_input_ticker",
                    label_visibility="collapsed"
                )
                
                from src.stock_lookup import resolve_stock_query, build_stock_directory
                resolved_code = ticker.strip()
                resolved_name = ticker.strip()
                if resolved_code:
                    matches = resolve_stock_query(resolved_code, build_stock_directory())
                    if matches:
                        selected = matches[0]
                        resolved_code = str(selected.get("code") or "")
                        resolved_name = str(selected.get("name") or "")
                        st.caption(f"已匹配：{resolved_name}（{resolved_code}）")
                    else:
                        st.warning("没有匹配到股票。可以尝试输入代码或更短的名称关键词。")
            
            with inner_cols[1]:
                st.markdown('<div class="command-field-label">分析日期</div>', unsafe_allow_html=True)
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

        # History Selection Area inside the container
        history = get_history()
        if history:
            with st.expander("历史投研报告", expanded=False):
                # Use inline script via st.markdown to force-style the history buttons and layout.
                # Using st.markdown instead of components.html() avoids creating an iframe
                # that takes space in the flex layout and causes a visible gap.
                st.markdown(
                    """
                    <script>
                    (() => {
                      const doc = document;
                      const fixHistoryLayout = () => {
                        // 1. Force expander content to horizontal flex row
                        const expanderDetails = doc.querySelectorAll('[data-testid="stExpanderDetails"]');
                        expanderDetails.forEach(detail => {
                          const hasHistBtn = detail.querySelector('[class*="st-key-ta_hist_"]');
                          if (!hasHistBtn) return;
                          const vBlock = detail.querySelector('[data-testid="stVerticalBlock"]');
                          if (vBlock) {
                            vBlock.style.setProperty('display', 'flex', 'important');
                            vBlock.style.setProperty('flex-direction', 'row', 'important');
                            vBlock.style.setProperty('flex-wrap', 'wrap', 'important');
                            vBlock.style.setProperty('align-items', 'center', 'important');
                            vBlock.style.setProperty('justify-content', 'flex-start', 'important');
                            vBlock.style.setProperty('gap', '6px 8px', 'important');
                            // Make each element-container auto width, hide empty ones
                            vBlock.querySelectorAll('[data-testid="element-container"]').forEach(el => {
                              el.style.setProperty('width', 'auto', 'important');
                              el.style.setProperty('flex', '0 0 auto', 'important');
                              el.style.setProperty('margin', '0', 'important');
                              el.style.setProperty('padding', '0', 'important');
                              // Hide containers that only have a script/style or iframe (the JS injection container)
                              if (!el.querySelector('[class*="st-key-ta_hist_"], [class*="st-key-ta_del_"]')) {
                                el.style.setProperty('display', 'none', 'important');
                              }
                            });
                          }
                        });

                        // 2. Force delete buttons to be tiny 20px solid pink circles
                        doc.querySelectorAll('[class*="st-key-ta_del_"] button').forEach(btn => {
                          btn.style.setProperty('width', '20px', 'important');
                          btn.style.setProperty('min-width', '20px', 'important');
                          btn.style.setProperty('max-width', '20px', 'important');
                          btn.style.setProperty('height', '20px', 'important');
                          btn.style.setProperty('min-height', '20px', 'important');
                          btn.style.setProperty('max-height', '20px', 'important');
                          btn.style.setProperty('padding', '0', 'important');
                          btn.style.setProperty('margin', '0', 'important');
                          btn.style.setProperty('border-radius', '50%', 'important');
                          btn.style.setProperty('border', 'none', 'important');
                          btn.style.setProperty('background', 'rgba(255, 92, 122, 0.8)', 'important');
                          btn.style.setProperty('color', '#fff', 'important');
                          btn.style.setProperty('display', 'inline-flex', 'important');
                          btn.style.setProperty('align-items', 'center', 'important');
                          btn.style.setProperty('justify-content', 'center', 'important');
                          btn.style.setProperty('overflow', 'hidden', 'important');
                          btn.style.setProperty('flex-shrink', '0', 'important');
                          btn.style.setProperty('box-shadow', '0 4px 10px rgba(255, 92, 122, 0.3)', 'important');
                        });

                        // 3. Force history pill button containers to tight margin
                        doc.querySelectorAll('[data-testid="element-container"]').forEach(el => {
                          const histChild = el.querySelector(':scope > [class*="st-key-ta_hist_"]');
                          const delChild = el.querySelector(':scope > [class*="st-key-ta_del_"]');
                          if (histChild) {
                            el.style.setProperty('margin-right', '-4px', 'important');
                            el.style.setProperty('z-index', '2', 'important');
                          }
                          if (delChild) {
                            el.style.setProperty('z-index', '1', 'important');
                            el.style.setProperty('display', 'flex', 'important');
                            el.style.setProperty('align-items', 'center', 'important');
                            el.style.setProperty('justify-content', 'center', 'important');
                          }
                        });
                      };

                       // Run immediately, then watch for DOM changes
                      fixHistoryLayout();
                      setTimeout(fixHistoryLayout, 100);
                      setTimeout(fixHistoryLayout, 500);
                      new MutationObserver(fixHistoryLayout).observe(doc.body, { childList: true, subtree: true });

                      doc.addEventListener("click", (event) => {
                        const cancelBtn = event.target.closest('[class*="st-key-cancel_del_btn"] button');
                        if (cancelBtn) {
                          const dialog = doc.querySelector('div[role="dialog"]');
                          const backdrop = doc.querySelector('[data-testid="stDialog"], [data-testid="stModal"]');
                          if (dialog) dialog.style.setProperty('display', 'none', 'important');
                          if (backdrop) backdrop.style.setProperty('display', 'none', 'important');
                          
                          const closeBtn = doc.querySelector('button[aria-label="Close"], [class*="stDialogHeader"] button, [data-testid="stDialog"] button');
                          if (closeBtn) closeBtn.click();
                        }
                      }, { passive: true });
                    })();
                    </script>
                    """,
                    unsafe_allow_html=True,
                )
                
                active_path = st.session_state.get("ta_viewing_history")
                for idx, entry in enumerate(history[:12]): # Show recent 12
                    t, d = entry["ticker"], entry["date"]
                    name = entry.get("company_name") or _resolve_stock_name(t)
                    label = f"{name} {t}\n{d}" if name else f"{t}\n{d}"
                    is_active = active_path == entry["path"]
                    
                    if st.button(label, key=f"ta_hist_{t}_{d}_{idx}", use_container_width=False, type="primary" if is_active else "secondary"):
                        st.session_state["ta_viewing_history"] = entry["path"]
                        st.session_state["ta_start_analysis"] = None
                        st.rerun()
                        
                    if st.button("✕", key=f"ta_del_{t}_{d}_{idx}", use_container_width=False):
                        st.session_state["ta_delete_target"] = entry
                        st.rerun()



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
        render_jocket_progress(tracker)
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
        # Empty state prompt using hero dashboard
        render_hero(
            code="未选择个股",
            data_source="自动更新",
            latest_date="-",
            updated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
            title="7 位 AI 分析师就绪",
            subtitle="在上方输入股票代码，启动多 Agent 深度投研系统。将依次执行：质量门控 → 独立投研 → 多空辩论 → 交易决策 → 风控评估。",
            ai_summary=None
        )
