# A Share Stock Picker

## Overview

`a-share-stock-picker` is a Codex skill for mainland A-share selection. It now supports two core operating modes:

- `Post-close / pre-open mode`: for watchlists, short/medium/long horizon selection, and conditional trade plans between the close and the next open
- `T+1 tail-entry mode`: for entering near the close of trading day `D` and selling on trading day `D+1`, which fits A-share `T+1` constraints better

This repository is a complete skill package rather than a plain prompt. It includes:

- `SKILL.md`: the core skill behavior definition
- `references/`: selection frameworks, price rules, output templates, tail-mode guidance, and usage notes
- `scripts/`: helpers for quotes, scoring, indicators, catalysts, intraday snapshots, and report generation
- `agents/`: agent configuration

## Best For

- `推荐股票`
- `盘前选股`
- `按收盘后信息做观察池`
- `给我短中长线标的`
- `给我条件交易计划`
- `尾盘选股`
- `尾盘买入、次日卖出`
- `按 A 股 T+1 规则做短线计划`

## Key Characteristics

- Mainland A-shares only
- Supports short-term, medium-term, and long-term analysis
- Uses verified market data instead of user-supplied prices
- Prefers `watchlist / candidate list / conditional trade plan` wording
- Avoids hard buy/sell claims when freshness or verification is insufficient
- Adds a dedicated `T+1 tail-entry mode` for practical same-day tail entry and next-day exit planning

## Repository Layout

```text
.
├── LICENSE
├── README.md
├── README.en.md
└── a-share-stock-picker
    ├── SKILL.md
    ├── agents/
    ├── references/
    └── scripts/
```

The actual folder to install into Codex is:

```text
a-share-stock-picker/a-share-stock-picker
```

## Operating Modes

### 1. Post-close / pre-open mode

Best for:

- building the next trading day watchlist after the close
- generating short/medium/long horizon candidates before the open
- writing conditional trade plans based on the latest completed session and overnight context

Characteristics:

- uses the latest completed trading session as the main price anchor
- if the local time is before `15:00` on trading day `D`, the anchor remains trading day `D-1`; if the local time is after `15:00` on trading day `D`, the anchor switches to trading day `D` close and the report becomes a `D+1` pre-open report
- interprets setups against 5-day, 20-60 day, and 6-12 month history windows
- defaults to `5` short-term, `5` medium-term, and `5` long-term names
- remains the default workflow for standard pre-open analysis

### 2. T+1 tail-entry mode

Best for:

- buying near the close of day `D`
- selling on day `D+1`
- avoiding the mismatch between same-day recommendations and A-share `T+1` rules

Characteristics:

- refreshes minute-level data during the final trading hour
- rescoring is based on post-`14:00` strength, late-session volume, close location, and recent structure
- outputs two linked plans:
  - `today tail-entry plan`
  - `next-day sell plan`

## Built-in Capabilities

### Data and analysis

- first prefilters roughly the top `200` valuable A-shares from Tonghuashun market ranking pages
- Fetches A-share quotes and recent price history
- Calculates MA, ATR, MACD clues, volume ratio, and related indicators
- Carries capital-flow signals such as inflow, outflow, net inflow, turnover value, and turnover rate into the actual analysis instead of using them only for prefiltering
- Uses major-capital flow as a real recommendation factor that can change ranking, core logic, and skip conditions instead of treating it as display-only commentary
- Pulls sector/industry context, news, announcements, policy clues, and supporting context
- Scores and buckets candidates into short-, medium-, and long-term groups
- Extracts intraday tail-session snapshots to measure post-`14:00` strength
- Does not fabricate evidence when sector, policy, or news verification is missing

### Output behavior

- Produces Chinese Markdown stock-picking reports
- Supports structured table output
- Uses a fixed standard-report template with fixed column order for both the default mode and the T+1 mode
- Prefers conditional trading language
- In tail mode, clearly separates the entry day from the sell day

## Main Scripts

### Post-close / pre-open mode

- `scripts/fetch_market_universe.py`
- `scripts/fetch_quotes.py`
- `scripts/fetch_ths_context.py`
- `scripts/build_watchlist.py`
- `scripts/fetch_catalysts.py`
- `scripts/indicators.py`
- `scripts/fetch_news_summary.py`
- `scripts/render_report.py`
- `scripts/run_picker.py`

### T+1 tail-entry mode

- `scripts/fetch_market_universe.py`
- `scripts/fetch_intraday_snapshot.py`
- `scripts/build_tail_watchlist.py`
- `scripts/fetch_ths_context.py`
- `scripts/render_t1_plan.py`
- `scripts/run_t1_tail_trade.py`

## Usage

### Install into Codex

```bash
cp -R a-share-stock-picker ~/.codex/skills/
```

### Example prompts

#### Post-close / pre-open mode

```text
Use $a-share-stock-picker to build a pre-open A-share watchlist with 5 short-term, 5 medium-term, and 5 long-term names.
```

```text
Use $a-share-stock-picker to generate a balanced candidate list and a conditional trade plan based on post-close information.
```

#### T+1 tail-entry mode

```text
Use $a-share-stock-picker in T+1 tail-entry mode and give me an A-share short-term plan that can be bought near today's close and sold tomorrow.
```

```text
Use $a-share-stock-picker after 14:30 to re-evaluate the market and output a tail-entry plan for today plus a sell plan for tomorrow.
```

### Recommended workflow

#### Post-close / pre-open mode

- Prefilter the market down to roughly the top 200 names first
- Fetch quotes and recent history next
- Add sector, news, policy, and disclosure context
- Produce a watchlist or conditional trade plan last

#### T+1 tail-entry mode

- `14:00-14:20`: pull intraday and historical structure
- `14:20-14:40`: score tail-entry quality
- `14:45-14:57`: produce the final tail-entry plan
- `D+1`: execute the sell plan

If exact entry, stop, or target levels are required, the underlying market data should be freshly verified first.

## Notes

- Post-close / pre-open mode is best for the close-to-next-open window
- The default pre-open output target is `5+5+5`
- Tail mode is better for practical A-share `T+1` short-term trading
- Avoid exact conclusions when intraday data has not been validated
- Fall back to watchlist or conditional-plan language when evidence is not strong enough

## License

This repository is licensed under the terms described in [LICENSE](./LICENSE).
