# T+1 Tail Entry Mode

Use this file when the user wants to buy near the close of trading day `D` and sell on trading day `D+1`.

## Why This Mode Exists

The default stock picker workflow is optimized for the post-close to pre-open window. That works well for a next-day opening-session plan, but it conflicts with A-share `T+1` rules when the user wants to react inside the same trading day.

This mode solves that by moving the short-term execution point to the final hour of trading on day `D`.

## Operating Window

Recommended time slices:

1. `14:00-14:20`: pull intraday data and refresh the candidate pool
2. `14:20-14:40`: score tail-entry quality and narrow to `5` names
3. `14:45-14:57`: output the final tail-entry plan and execute only if the trigger still holds
4. `D+1 09:20-09:30`: refresh the overnight context
5. `D+1 09:30-10:30`: execute the main sell plan

## Data Requirements

For each final candidate, use:

- `last.js` for recent `5/20/60` day structure
- `v6/time/.../defer/last.js` for day `D` minute-by-minute path
- current-day price position versus previous close
- current-day price position within the intraday range
- change from `14:00`
- late-session volume share
- liquidity filters such as recent成交额

Do not rely on a same-day move alone. Tail-entry decisions must still be read against the recent `5-20` day structure.

## Tail-Entry Scoring

Favor names that show:

- good liquidity
- tail-session strength after `14:00`
- a close near the session high
- acceptable extension relative to the recent `5` day range
- enough space to a next-day first target

Avoid names that show:

- one-word or nearly untradable boards
- excessive same-day extension
- weak late-session follow-through
- thin liquidity
- isolated rumor-driven spikes without sector support

## Output Shape

When this mode is used, produce two linked plans:

1. `今日尾盘建仓计划`
2. `次日卖出计划`

The important shift is that buy and sell instructions are no longer written as if they happen on the same day.

Default output size for this mode:

- `5` tail-entry candidates per run when enough qualified names are available

The `今日尾盘建仓计划` table must use this exact column order:

`股票 | 优先级 | D日开盘价 | D日参考价 | 形态类型 | 板块强度 | 消息日期 | 资金净流入 | 资金面 | 尾盘支撑 | 尾盘阻力 | 核心逻辑 | 建仓时间 | 建仓价格区间 | 隔夜止损线 | 次日止盈一 | 次日止盈二 | 风险收益比 | 仓位建议 | 证据级别 | 数据时间戳 | 次日卖出时间 | 预计持有 | 放弃条件`

Use this Markdown table skeleton:

```markdown
| 股票 | 优先级 | D日开盘价 | D日参考价 | 形态类型 | 板块强度 | 消息日期 | 资金净流入 | 资金面 | 尾盘支撑 | 尾盘阻力 | 核心逻辑 | 建仓时间 | 建仓价格区间 | 隔夜止损线 | 次日止盈一 | 次日止盈二 | 风险收益比 | 仓位建议 | 证据级别 | 数据时间戳 | 次日卖出时间 | 预计持有 | 放弃条件 |
|---|---:|---:|---:|---|---|---|---:|---|---:|---:|---|---|---|---:|---:|---:|---|---|---|---|---|---|---|
| 示例股票 `000000` | 1 | 10.00 | 10.20 | 趋势型 | 较强(代理) | 2026-03-19 | +1.26亿 | 净流入偏强 | 9.85 | 10.60 | 一句话说明逻辑 | D日 14:50-14:57 | 10.00-10.12 | 9.78 | 10.60 | 11.00 | 1:2.1 | 轻仓 | 高 | 2026-03-19 1451 | D+1 9:30-10:30 优先处理 | 隔夜到次日 1 个交易日为主 | 高开过多、尾盘回落、流动性骤降或主力资金明显净流出时放弃 |
```

Do not compress this mode into a shorter freeform summary when the user asked for the standard report.

## Execution Rules

- Only execute near the close if the tail trigger is still valid
- If price fades and breaks the tail support before the close, cancel the plan
- Do not chase if the price runs far above the planned entry zone in the last minutes
- On day `D+1`, prefer staged selling:
  - strong gap-up: trim early
  - flat open: use the first target
  - weak open: enforce protection early

## Script Chain

Use this pipeline:

1. `scripts/fetch_quotes.py`
2. `scripts/fetch_intraday_snapshot.py`
3. `scripts/build_tail_watchlist.py`
4. `scripts/fetch_catalysts.py`
5. `scripts/fetch_news_summary.py`
6. `scripts/render_t1_plan.py`
7. or `scripts/run_t1_tail_trade.py`
