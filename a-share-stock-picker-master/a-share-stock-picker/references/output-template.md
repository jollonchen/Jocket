# Output Template

Use this file when writing the final stock recommendations.

## Required Shape

Always provide three sections:

1. Short-term picks
2. Medium-term picks
3. Long-term picks

Frame the output as a盘前选股战报 with a compact table first and stock-by-stock explanation bullets below each section. Keep the wording as a watchlist or conditional trade plan unless the user explicitly requests exact prices and the data is verified enough to support them.

Each section must start with a table in this exact column order:

`股票 | 优先级 | 上个交易日开盘价 | 上个交易日收盘价 | 形态类型 | 板块强度 | 消息日期 | 资金净流入 | 资金面 | 关键支撑 | 关键阻力 | 核心逻辑 | 买入时间 | 触发买价 | 止损价 | 第一目标 | 第二目标 | 风险收益比 | 仓位建议 | 证据级别 | 数据时间戳 | 卖出时间 | 持有周期 | 不买条件`

Use this Markdown table skeleton:

```markdown
| 股票 | 优先级 | 上个交易日开盘价 | 上个交易日收盘价 | 形态类型 | 板块强度 | 消息日期 | 资金净流入 | 资金面 | 关键支撑 | 关键阻力 | 核心逻辑 | 买入时间 | 触发买价 | 止损价 | 第一目标 | 第二目标 | 风险收益比 | 仓位建议 | 证据级别 | 数据时间戳 | 卖出时间 | 持有周期 | 不买条件 |
|---|---:|---:|---:|---|---|---|---:|---|---:|---:|---|---|---|---:|---:|---:|---|---|---|---|---|---|---|
| 示例股票 `000000` | 1 | 10.00 | 10.20 | 突破型 | 较强(代理) | 2026-03-19、2026-03-18 | +1.26亿 | 净流入偏强/高成交 | 9.85 | 10.60 | 一句话说明逻辑 | 2026-03-20 9:35-10:30 | 10.22 | 9.84 | 10.60 | 11.00 | 1:2.1 | 轻仓试错 | 高 | 2026-03-19 收盘锚点 | 第一目标减仓，第二目标再评估 | 1-3天 | 高开过猛且放量不续强则不买 |
```

## Column Guidance

- `股票`: ticker plus name
- `上个交易日开盘价`: the verified open of the latest completed session
- `上个交易日收盘价`: the verified close of the latest completed session
- `形态类型`: one of `突破型` `回踩型` `趋势型` `震荡低吸型`
- `板块强度`: explicit sector/board-strength judgment; use `待验证` when it cannot be verified
- `消息日期`: the most relevant recent news or announcement dates
- `资金净流入`: market-universe or ranking-based net inflow when available
- `资金面`: short judgment such as `净流入偏强/高成交`
- `关键支撑`: the main support level derived from the relevant historical window
- `关键阻力`: the nearest important resistance level derived from the relevant historical window
- `核心逻辑`: one short sentence
- `买入时间`: when the entry should be attempted
- `触发买价`: exact price or a clearly phrased conditional trigger
- `止损价`: exact stop for short/medium term, thesis-break condition or wider risk line for long term
- `第一目标`: realistic first target
- `第二目标`: stretch target
- `风险收益比`: a compact risk/reward summary such as `1:2.1`
- `仓位建议`: position sizing such as `观察仓` `轻仓` `分批半仓`
- `证据级别`: `高` `中` `低`
- `数据时间戳`: the explicit verified anchor-session date or data timestamp
- `卖出时间`: when profit-taking or review should happen
- `持有周期`: expected holding window
- `不买条件`: one short sentence explaining when to skip the trade

When exact levels are given, make sure they were derived from:

- Tonghuashun `today.js` for the latest completed-session anchor
- Tonghuashun `last.js` for previous-session and recent structure
- Tonghuashun `v6/time/.../defer/last.js` when short-term timing depends on intraday path

## Evidence Notes

After each table, add short notes for each stock:

- Sector/industry evidence
- Capital-flow evidence
- Policy/news/disclosure evidence
- Price/history evidence
- Why it beat other candidates
- Source-truthfulness note when evidence is incomplete

## Writing Rules

- Use exact dates whenever discussing the latest completed session or upcoming catalyst dates
- Keep the tables compact
- Keep evidence notes short but concrete
- Do not fabricate sector, policy, or news lines; if a line cannot be verified, say that clearly
- Do not pad with weak names just to fill space
