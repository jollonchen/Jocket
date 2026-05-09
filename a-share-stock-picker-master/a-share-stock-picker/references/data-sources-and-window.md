# Data Sources And Window

Use this file when collecting data for the A-share stock picker.

## Default Window

This skill is built for:

- Previous trading day close
- Through the overnight news window
- Up to the next trading day open

Treat the latest completed session as the primary price anchor.

## Tail-Entry Window

When the user explicitly wants a same-day tail entry for a `T+1` exit:

- collect the full recent historical window as usual
- add same-day minute data from `v6/time/.../defer/last.js`
- use `14:00-15:00` as the execution analysis window
- treat the current trading day as the entry day `D`
- treat the next trading day as the sell day `D+1`

In this mode, the buy plan should be written for day `D` tail execution and the sell plan for day `D+1`, instead of pretending both happen on the same day

## Source Priority

For A-shares, collect price and market data in this order:

1. Tonghuashun market-wide ranking pages for the first-pass universe when no tickers are provided
2. Tonghuashun machine-readable K-line and time-series endpoints
3. Tonghuashun stock, quote, concept, industry, and market pages
4. Fallback public quote pages such as Eastmoney and Sina when Tonghuashun is unavailable
5. Official exchange or company disclosures
6. Official policy releases
7. Reputable financial media for context

Prefer the bundled script `scripts/fetch_quotes.py` to probe multiple sources quickly before composing the final answer.

Primary Tonghuashun entry points:

- `https://data.10jqka.com.cn/funds/ggzjl/field/<field>/order/desc/page/<page>/`
- `https://d.10jqka.com.cn/v2/line/<market>_<ticker>/01/today.js`
- `https://d.10jqka.com.cn/v2/line/<market>_<ticker>/01/last.js`
- `https://d.10jqka.com.cn/v6/time/hs_<ticker>/defer/last.js`
- `https://stockpage.10jqka.com.cn/<ticker>/`
- `https://basic.10jqka.com.cn/<ticker>/`
- `https://q.10jqka.com.cn/`
- related Tonghuashun article, notice, report, doctor, search, and data pages reachable from the stock page
- paginated Tonghuashun "更多" pages when they continue to return usable content

Market code mapping:

- `sh_<ticker>` for Shanghai A-shares
- `sz_<ticker>` for Shenzhen A-shares
- `hs_<ticker>` for Tonghuashun time-series endpoints

Field mapping for the preferred machine-readable endpoints:

- In `today.js`: `1` = trading date, `7` = open, `8` = high, `9` = low, `11` = close, `13` = volume, `19` = amount, `1968584` = turnover
- In `last.js`: each row is `date,open,high,low,close,volume,amount,turnover,...`
- In `v6/time/.../defer/last.js`: `pre` = previous close, `date` = trading date, `data` = minute-by-minute sequence, useful for intraday path and late-session behavior

Use `today.js` and `last.js` first whenever you need exact prices. Use Tonghuashun HTML and related pages for reports, news, diagnosis text, announcements, concept/industry context, and any stock-specific narrative that does not live in the machine-readable K-line endpoints.

Do not treat a single stock page as the whole evidence set. If Tonghuashun exposes additional linked pages and paginated "更多" pages for the same ticker, keep collecting them until:

- the page starts returning no new usable items
- pagination reaches a reasonable cap for the current task
- or the extra pages clearly stop adding decision-useful information

Useful-information rule:

- prefer fresh news and recent market-sensitive updates
- stale news should not outweigh a new price move or a new official disclosure

## Required Data Pull

For every final candidate, proactively retrieve:

- Previous trading session open
- Previous trading session close
- Latest completed-session open
- Latest completed-session close
- The relevant historical window, not just the anchor day
- Short term history: at least recent `5` trading days, and preferably recent `10` trading days for resistance/support context
- Medium term history: at least recent `20` trading days, and preferably recent `60` trading days for base and trend context
- Long term history: at least recent `6` months, and preferably recent `12` months for valuation and trend context
- Recent highs and lows
- Turnover and成交额
- Sector or concept strength
- A relevant policy, news, or company catalyst
- At least one official disclosure when available

Do not use user-supplied prices as a source of truth.

## Freshness Rules

- Short-term exact prices must be anchored to the latest completed session
- Medium-term exact prices must be anchored to the latest completed session plus recent 20-60 day structure
- Long-term entry zones must be anchored to recent 6-12 month valuation and price context
- If `today.js` is available, use it as the price anchor for the latest completed session
- If `last.js` includes a trailing synthetic row with missing open or high/low values, ignore that row and use the last complete daily row instead
- If `today.js` and the visible HTML snippet disagree, trust the machine-readable endpoint first and mention the date explicitly
- Use `v6/time/.../defer/last.js` to confirm whether a short-term setup finished strong or faded into the close
- Do not let the latest completed session override the broader structure if the recent 5-day, 20-day, or 60-day trend says the move is already weakening

If the latest verified price is stale or inconsistent, switch to conditional language instead of fake precision.
