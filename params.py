with st.container(border=True):
    st.markdown('<div class="command-bar-title">参数与操作</div>', unsafe_allow_html=True)
    if page == "个股分析":
        def _update_stock_start():
            val = st.session_state.get("stock_window_segment")
            if val:
                st.session_state["start_date"] = _start_date_for_trading_days(val).date()
        
        command_cols = st.columns([0.34, 0.18, 0.30, 0.18], vertical_alignment="bottom")
        with command_cols[0]:
            stock_query = st.text_input(
                "股票代码 / 名称",
                placeholder="输入 600519、贵州茅台、茅台等",
                help="支持 6 位股票代码、完整中文名和中文名称模糊匹配。",
                key="stock_query",
                autocomplete="off",
            )
        with command_cols[1]:
            start = st.date_input("行情日期", key="start_date", help="快捷按钮会自动重算行情起始日期。")
        with command_cols[2]:
            st.segmented_control(
                "观察窗口",
                options=[14, 30, 60],
                default=None,
                format_func=lambda x: f"近{x}日",
                key="stock_window_segment",
                on_change=_update_stock_start,
            )
        with command_cols[3]:
            run = st.button("启动雷达", type="primary", use_container_width=True, key="run_个股分析")

        matches = resolve_stock_query(stock_query, _stock_directory()) if stock_query.strip() else []
        if matches:
            selected = matches[0]
            code = str(selected.get("code") or "")
            name = str(selected.get("name") or "")
            st.caption(f"已匹配：{name}（{code}）")
        elif stock_query.strip():
            st.warning("没有匹配到股票。可以尝试输入 6 位代码、完整名称或更短的名称关键词。")

        with st.expander("DCF 估值假设", expanded=False):
            dcf_cols = st.columns(5, vertical_alignment="bottom")
            with dcf_cols[0]:
                dcf_years = st.number_input("DCF 年数", min_value=1, max_value=10, value=5, step=1)
            with dcf_cols[1]:
                dcf_growth = st.slider("现金流增长率", min_value=-20.0, max_value=30.0, value=5.0, step=0.5)
            with dcf_cols[2]:
                dcf_terminal_growth = st.slider("永续增长率", min_value=-5.0, max_value=6.0, value=2.0, step=0.25)
            with dcf_cols[3]:
                dcf_discount = st.slider("折现率", min_value=4.0, max_value=20.0, value=10.0, step=0.5)
            with dcf_cols[4]:
                dcf_margin = st.slider("安全边际", min_value=0.0, max_value=50.0, value=20.0, step=1.0)
    elif page == "市场情绪":
        sentiment_cols = st.columns([0.22, 0.32, 0.14, 0.14, 0.18], vertical_alignment="bottom")
        with sentiment_cols[0]:
            sentiment_date = st.date_input("交易日", value=sentiment_date, key="sentiment_date")
        with sentiment_cols[1]:
            sentiment_window = int(
                st.segmented_control(
                    "观察窗口",
                    options=[14, 30, 60],
                    default=60,
                    format_func=lambda x: f"近{x}日",
                    key="sentiment_window_segment",
                )
                or 60
            )
        with sentiment_cols[2]:
            sentiment_refresh = st.toggle("强制刷新", value=False, help="打开后会跳过页面级缓存，重新拉取公共接口。")
        with sentiment_cols[3]:
            sentiment_backfill = st.toggle("补齐历史", value=False, help="默认只拉交易日当日数据；打开后会尝试补齐观察窗口内历史涨跌停池。")
        with sentiment_cols[4]:
            run = st.button("启动雷达", type="primary", use_container_width=True, key="run_市场情绪")
    else:
        assistant_status = AIMarketAssistant(config, provider="gemini")
        ai_cols = st.columns([0.78, 0.22], vertical_alignment="center")
        with ai_cols[0]:
            st.caption(f"当前 API：Gemini · {'已连接' if assistant_status.ready() else '未配置'}")
        with ai_cols[1]:
            if st.button("新对话", use_container_width=True):
                st.session_state.pop("ai_market_messages", None)

