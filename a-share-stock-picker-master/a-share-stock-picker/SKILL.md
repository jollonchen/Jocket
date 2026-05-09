---
name: a-share-stock-picker
description: Analyze mainland A-share candidates across short-, medium-, and long-term horizons using the latest completed session as the price anchor plus recent history, market context, policy/news catalysts, and official disclosures. Use when asked to review, rank, or produce an A-share watchlist or trading plan for the post-close to pre-open window, especially requests such as "推荐股票", "盘前选股", "给我短中长线标的", or "按收盘后信息做观察池/交易计划". Do not use for blind direct buy/sell touting without evidence; prefer evidence-based watchlists and conditional plans.
---

# A Share Stock Picker

## Overview

Recommend mainland A-share candidates for three horizons in one pass: short term, medium term, and long term. Use the latest completed trading session plus overnight information up to the answer time.

Default to an evidence-based watchlist with conditional entry plans rather than unconditional "buy these tomorrow" language. If the user explicitly wants exact entry, stop, and target levels, provide them only when the underlying price data is fresh and verified.

In addition to the default post-close to pre-open workflow, this skill can also run a dedicated `T+1 tail-entry mode` for users who want to buy near the close of day `D` and sell on day `D+1`.

When `T+1 tail-entry mode` is used, default to exactly `5` tail-entry candidates per run when enough qualified names are available.

The same market-universe prefilter, quote verification, broader Tonghuashun context collection, sector/news/policy analysis, and truthfulness rules apply to both the default post-close / pre-open workflow and the `T+1 tail-entry mode`. The tail-entry mode only adds intraday and late-session requirements on top of the same evidence standards.

Only cover mainland A-shares. Do not recommend Hong Kong stocks, US equities, ETFs, funds, or convertibles unless the user explicitly asks for them.

## Scripts

Use bundled scripts when possible:

- `scripts/fetch_market_universe.py [limit]`: build a market-wide A-share prefilter universe from Tonghuashun ranking pages and keep the most valuable roughly `200` stocks
- `scripts/fetch_quotes.py <ticker...>`: fetch machine-readable Tonghuashun data plus public fallback sources for one or more A-share tickers
- `scripts/fetch_ths_context.py <ticker...>`: fetch broader Tonghuashun context across stock, basic, article, and paginated "more" pages when available
- `scripts/build_watchlist.py <quotes.json>`: score candidates and convert fetched quote data into short/medium/long watchlist buckets
- `scripts/fetch_catalysts.py <ticker...>`: derive catalyst/title clues from the broader Tonghuashun multi-page context payload
- `scripts/indicators.py <quotes.json>`: calculate basic technical indicators such as MA, ATR, MACD clue, and volume ratio
- `scripts/fetch_news_summary.py <ticker...>`: derive a compact summary from the broader Tonghuashun multi-page context payload
- `scripts/render_report.py <watchlist.json> [catalysts.json] [indicators.json] [news_summary.json]`: render a Chinese markdown watchlist report with names, sectors, indicators, and conditional trade-plan wording
- `scripts/run_picker.py <ticker...>`: one-shot entry point that fetches quotes, scores candidates, pulls catalyst clues, computes indicators, and writes the final report
- `scripts/fetch_intraday_snapshot.py <quotes.json>`: turn minute-level Tonghuashun data into a tail-session snapshot for day `D`
- `scripts/build_tail_watchlist.py <quotes.json> <intraday_snapshot.json>`: score candidates for `T+1` tail entry quality
- `scripts/render_t1_plan.py <tail_watchlist.json> [catalysts.json] [news_summary.json]`: render a `D日尾盘建仓 / D+1卖出` markdown plan
- `scripts/run_t1_tail_trade.py <ticker...>`: one-shot entry point for the `T+1` tail-entry workflow

## Operating Window

Default operating window:

- Start: after the previous trading day officially closes
- End: before the next trading day opens

Use the latest completed session as the main price anchor. Add overnight policy, company, and macro updates that arrive before the answer is produced.

Anchor-date rule for the default post-close / pre-open workflow:

- if the current local time is before the A-share cash-session close on trading day `D`, treat trading day `D-1` as the latest completed session
- if the current local time is after the A-share cash-session close on trading day `D`, treat trading day `D` as the latest completed session and write the report as trading day `D+1` pre-open context
- when the user appears to mix up `today`, `tomorrow`, `盘前`, or the anchor date, explicitly state both absolute dates in the answer
- do not write a `D+1` pre-open report using `D-1` prices when trading day `D` has already closed

If the user asks during trading hours, say that this skill is optimized for the post-close to pre-open window and adapt cautiously.

Alternative operating window for `T+1 tail-entry mode`:

- Start: roughly `14:00` on trading day `D`
- Decision window: `14:20-14:57` on trading day `D`
- Exit window: next trading day `D+1`

Use recent historical structure plus same-day minute data to decide whether a tail entry is still tradable. Do not write same-day buy and same-day sell instructions for A-shares as if they were directly executable.

## Workflow

### 1. Confirm the scope

Assume the user wants:

- Exactly 5 short-term A-share picks
- Exactly 5 medium-term A-share picks
- Exactly 5 long-term A-share picks

Do not duplicate names across horizons by default. Reuse a name across horizons only if it is unusually strong and you explicitly justify the overlap.

### 2. Pull data proactively

Always fetch market data yourself. Do not rely on the user to provide prices.

When the user does not provide a ticker list, do not attempt to reason over the entire market blindly. First build a market-wide prefilter universe of roughly `200` A-shares from Tonghuashun ranking pages, then run the deeper quote/context analysis on that smaller universe, and finally recommend only the best `5` names for the short-term workflow.

For A-shares, start with a Tonghuashun market-wide prefilter universe when no ticker list is supplied, then use bundled probing scripts and machine-readable endpoints, and finally broader Tonghuashun context pages:

- `scripts/fetch_market_universe.py [limit]`
- `scripts/fetch_quotes.py <ticker...>`
- `scripts/fetch_ths_context.py <ticker...>`
- `https://d.10jqka.com.cn/v2/line/<market>_<ticker>/01/today.js`
- `https://d.10jqka.com.cn/v2/line/<market>_<ticker>/01/last.js`
- `https://d.10jqka.com.cn/v6/time/hs_<ticker>/defer/last.js`
- `https://stockpage.10jqka.com.cn/<ticker>/`
- `https://basic.10jqka.com.cn/<ticker>/`
- `https://q.10jqka.com.cn/`
- Eastmoney and Sina public quote pages as fallback context sources

Where:

- `<market>` is `sh` for Shanghai tickers and `sz` for Shenzhen tickers
- `<ticker>` is the 6-digit A-share code

Use the endpoints in this order:

1. `today.js` for the latest completed session's exact open, high, low, close, amount, and turnover
2. `last.js` for recent daily history and the previous trading session's open and close
3. `v6/time/.../defer/last.js` for intraday or same-day minute structure when needed
4. broader Tonghuashun stock, basic, article, and paginated "more" pages for news, reports, announcements, diagnosis, sector strength, and concept context

Use them to retrieve:

- Latest completed-session close
- Latest completed-session open
- Recent highs and lows
- Recent turnover,成交额, and volume behavior
- Recent资金流入、资金流出、资金净流入 when available from Tonghuashun market ranking sources
- Sector or concept strength
- Recent relative performance
- Same-day minute path when short-term execution depends on intraday behavior
- Company news, announcements, research reports, diagnosis text, concept tags, and other stock context from multiple Tonghuashun pages

Do not rely on a single Tonghuashun HTML page when richer context is available. If Tonghuashun exposes multiple related pages or "more" links for the stock, follow them and continue through pagination when the additional pages still return usable content.

Filter that broader context aggressively:

- keep only decision-useful items instead of dumping thousands of weak lines
- prefer fresh news; do not let half-year-old news dominate a short-term conclusion
- keep announcements, reports, and diagnosis/context pages only when they still add decision value

Minimum history windows:

- Short term: at least 5 trading days
- Medium term: at least 20-60 trading days
- Long term: at least 6-12 months

Never base a recommendation on the latest completed session alone. The latest day is only the anchor day. Every recommendation must be interpreted against the relevant historical window above.

If an exact buy or sell price is provided, it must be anchored to the latest completed session and recent price structure. Do not invent precise levels from stale data.

If Tonghuashun exposes a machine-readable price endpoint, prefer it over scraping visible HTML text from the page.

### 3. Build the evidence pack

For each candidate, collect evidence from three buckets:

1. Price and market structure
2. Policy, news, or company-specific catalysts
3. Official disclosures or company fundamentals

Every final pick should have at least:

- One price/volume reason
- One capital-flow reason when market-wide or per-stock fund-flow data is available
- One policy/news/company-event reason
- One structural reason such as industry position, earnings trend, or valuation support
- One clear sector/industry interpretation

If sector, policy, or news evidence is missing, say that explicitly. Never fabricate a policy line, a sector driver, or a news catalyst just to make the write-up look complete.

Prefer:

- Tonghuashun quote and market pages for price/history/context
- Tonghuashun multi-page stock context, including paginated "more" pages when they return usable content
- Exchange and company disclosures for official facts
- Official policy sources and reputable financial media for catalyst context

Source-truthfulness rule:

- every recommendation should be traceable to fetched price/history/context data
- if a policy or news catalyst cannot be verified from the fetched sources, write `暂无自动抓取到可信政策线索` or equivalent instead of inventing one
- do not turn sector guesswork into asserted fact
- when evidence is incomplete, lower confidence and keep the wording conditional

### 3A. Build the market-wide prefilter universe first

For short-term and `T+1` workflows without user-supplied tickers:

1. fetch a Tonghuashun market-wide prefilter universe
2. rank by liquidity and activity first
3. keep only about `200` stocks in the first-pass universe
4. use factors including but not limited to:
   -成交额
   -换手率
   -资金净流入
   -涨跌幅/活跃度
5. only after that, fetch the deeper quote/history/context payloads for the selected universe
6. carry the market-universe资金流向 metrics into the final scoring and report whenever they are available; do not stop at prefilter only
7. treat 主力资金流向 as a real recommendation factor, not a display-only note:
   - positive 主力净流入 can raise priority and tradability
   - persistent 主力净流出 should lower priority or trigger a skip condition
   - in T+1 mode, obvious 主力净流出 should directly weaken tail-entry willingness

### 4. Score by horizon

Use the horizon-specific framework in the references:

- Short term: momentum, sentiment, turnover, trigger quality, next-session tradability
- Medium term: earnings momentum, estimate revisions, 20-60 day structure, next-quarter catalysts
- Long term: business quality, balance sheet, valuation band, long-duration thesis

When the user wants exact buy, stop, or target prices, also load:

- `references/price-plan-rules.md`

### 5. Produce the final list

Default output:

- 5 short-term picks
- 5 medium-term picks
- 5 long-term picks

Format-lock rule for the final answer:

- when the user asks for the standard report, do not improvise a shorter summary layout
- for the default post-close / pre-open mode, follow `references/output-template.md` exactly, including section structure and exact table column order
- for the `T+1 tail-entry mode`, follow `references/t1-tail-mode.md` exactly, including the exact table column order for `今日尾盘建仓计划`
- do not silently drop columns such as `资金净流入` or `资金面`
- if evidence is missing, keep the column and write `待确认` instead of changing the format

If you genuinely cannot support 5 high-quality names for a horizon, say that clearly and explain what evidence is missing. Do not pad with weak names just to fill the quota.

Prefer "观察池 / 候选名单 / 条件计划" wording. When a direct buy recommendation would be too speculative, convert the answer into conditional language such as:

- `若明日放量站稳前高再看`
- `仅在回踩支撑不破时考虑`
- `高开过多则放弃`

### 6. Switch modes when the user wants tail entry

If the user explicitly wants a short-term plan that can be bought before the close and sold the next day, switch from the default pre-open mode to `T+1 tail-entry mode`.

In that mode:

1. use the normal workflow to build a larger candidate pool first when practical
2. fetch same-day minute data in the final trading hour
3. score names for tail strength, liquidity, and next-day tradability
4. narrow the final tail-entry list to `5` names when enough qualified candidates exist
5. output two linked plans:
   - `今日尾盘建仓计划`
   - `D+1卖出计划`
6. make sure the buy instructions are for day `D` and the sell instructions are for day `D+1`
7. if the tail trigger weakens before the close, cancel the entry instead of forcing a trade

Recommended prompt templates for this mode:

- `14:10` pre-screen:
  `使用 $a-share-stock-picker 按 T+1 尾盘建仓模式，先做一版预备观察池。请基于当前盘中信息，输出今日尾盘可买、次日可卖的 A 股短线计划，先给我 5 个候选，并标出优先级。`
- `14:30+` final refresh:
  `使用 $a-share-stock-picker 在 14:30 之后重新分析。请输出今日尾盘建仓计划和次日卖出计划，按 T+1 模式给我 5 个最终候选，并按可执行优先级排序。`
- `D+1 09:25` sell review:
  `使用 $a-share-stock-picker 复核我昨天的 T+1 尾盘建仓计划。请结合今日竞价和开盘前信息，输出这 5 只的今日卖出优先级、止盈位、止损位和放弃条件。`

Wording rule:

- on trading day `D`, write `今日尾盘建仓计划` + `次日卖出计划`
- on trading day `D+1`, if reviewing yesterday's tail-entry plan, write `今日卖出计划` instead of `明日卖出计划`

## Safety And Quality Guardrails

- Do not pretend to have live verified prices if the sources cannot be fetched.
- Do not invent exact buy, stop, or target levels from stale or conflicting data.
- Do not invent sector, policy, macro, or news rationales that were not verified from fetched sources.
- Do not force all 9 names if the evidence quality is weak.
- Prefer large, liquid, information-rich names when the user asks for a balanced style.
- If the market regime is unclear, say so and bias toward watchlist language and risk controls.

## Output Standard

Use three sections in this order:

1. Short-term picks
2. Medium-term picks
3. Long-term picks

Each section should start with a compact table:

`股票 | 优先级 | 上个交易日开盘价 | 上个交易日收盘价 | 形态类型 | 板块强度 | 消息日期 | 关键支撑 | 关键阻力 | 核心逻辑 | 买入时间 | 触发买价 | 止损价 | 第一目标 | 第二目标 | 风险收益比 | 仓位建议 | 证据级别 | 数据时间戳 | 卖出时间 | 持有周期 | 不买条件`

Write the section as a Markdown table in this shape:

```markdown
| 股票 | 优先级 | 上个交易日开盘价 | 上个交易日收盘价 | 形态类型 | 板块强度 | 消息日期 | 关键支撑 | 关键阻力 | 核心逻辑 | 买入时间 | 触发买价 | 止损价 | 第一目标 | 第二目标 | 风险收益比 | 仓位建议 | 证据级别 | 数据时间戳 | 卖出时间 | 持有周期 | 不买条件 |
|---|---:|---:|---:|---|---|---|---:|---:|---|---|---|---:|---:|---:|---|---|---|---|---|---|---|
| 示例股票 `000000` | 1 | 10.00 | 10.20 | 突破型 | 较强(代理) | 2026-03-19、2026-03-18 | 9.85 | 10.60 | 一句话说明逻辑 | 2026-03-20 9:35-10:30 | 10.22 | 9.84 | 10.60 | 11.00 | 1:2.1 | 轻仓试错 | 高 | 2026-03-19 收盘锚点 | 第一目标减仓，第二目标再评估 | 1-3天 | 高开过猛且放量不续强则不买 |
```

Below each table, add short evidence notes for each name:

- Which sector/industry it belongs to and why that matters
- Why it was selected
- Which policy/news/disclosure mattered
- Which price/history facts mattered
- If policy/news evidence is missing, say so directly instead of filling the gap with speculation

## Price Rules

- Exact price levels must be based on the latest completed session plus recent history
- Every stock row must include the previous trading session's open and close
- Prefer `today.js` for the current anchor day and `last.js` for the previous session and recent daily structure
- Use `v6/time/.../defer/last.js` only as a supplement for minute-path confirmation, not as the sole source for previous-session OHLC
- Never derive buy, stop, or target levels from same-day OHLC alone; use the relevant 5-day, 20-60 day, or 6-12 month structure first
- Exact prices are allowed only when the anchor price is fresh and clearly verified
- If freshness or verification is insufficient, switch to conditional trigger language
- If a new verified price conflicts with an older working price, discard the old plan immediately

## Buy And Sell Timing Rules

Use horizon-appropriate timing language:

- Short term: next trading day opening session, early pullback, breakout confirmation, or next 1-3 trading days
- Medium term: next 1-5 trading days for entry, next 2-12 weeks for exit or review
- Long term: staged entry over the next 5-20 trading days, thesis review over 6-24 months

When giving exact levels, explain them as structure-based levels derived from Tonghuashun session data, recent highs/lows, and turnover behavior rather than as guarantees.

## Reference Files

Load:

- `references/data-sources-and-window.md` for source priority and operating window
- `references/horizon-selection-framework.md` for short/medium/long scoring
- `references/price-plan-rules.md` for buy, stop, and target derivation
- `references/output-template.md` for the final answer format
- `references/usage-notes.md` for watchlist-first phrasing and balanced-style response shaping
- `references/t1-tail-mode.md` for the dedicated `T+1` tail-entry workflow
