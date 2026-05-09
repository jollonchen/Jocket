# Price Plan Rules

Use this file when the user wants exact buy prices, stop-loss levels, target prices, or explicit buy/sell timing.

## Core Principle

Derive every price plan from verified Tonghuashun session data, not from guesswork.

Do not use the latest completed session in isolation. First read the relevant historical window, then interpret the latest session inside that larger structure.

Minimum inputs before giving exact numbers:

- Latest completed-session open, high, low, and close from `today.js`
- Previous trading session open, high, low, and close from `last.js`
- Recent structure from `last.js`
- Intraday path from `v6/time/.../defer/last.js` when short-term execution quality matters

If any of these are missing or inconsistent, downgrade to conditional trigger language instead of fake precision.

## Fixed Calculation Sequence

Always follow this order before writing `触发买价`, `止损价`, `第一目标`, or `第二目标`:

1. Determine the horizon: short term, medium term, or long term
2. Pull the required historical window for that horizon
3. Identify the setup type:
   - `突破型`
   - `回踩型`
   - `趋势型`
   - `震荡低吸型`
4. Mark the key structure levels from the historical window:
   - Recent highs
   - Recent lows
   - Recent close cluster
   - Most recent support and resistance
5. Use the latest completed session only as the anchor day to confirm:
   - Whether momentum strengthened or weakened
   - Whether turnover expanded or faded
   - Whether the close location supports continuation
6. Derive:
   - `触发买价`
   - `止损价`
   - `第一目标`
   - `第二目标`
   - `风险收益比`
7. Sanity-check the risk/reward and reject the setup if the structure is poor

Never skip from the latest completed session directly to exact price levels.

## Structure Checklist

Before setting levels, identify:

- Latest completed-session close
- Latest completed-session high and low
- Previous trading session close
- Recent 5-day high and low
- Recent 20-day high and low for medium term
- Recent 60-day or 6-12 month structure for long term
- Whether the stock closed near the high, near the low, or in the middle of the range
- Whether turnover and成交额 were expanding, stable, or fading

Required structure windows by horizon:

- Short term: recent `5` trading days minimum, recent `10` trading days preferred
- Medium term: recent `20` trading days minimum, recent `60` trading days preferred
- Long term: recent `6` months minimum, recent `12` months preferred

Treat the latest completed session as the anchor day unless the user explicitly asks for a historical plan.

## Short-Term Rules

Use for next trading day to roughly 5 trading days.

Preferred setup types:

1. Breakout continuation
2. Early pullback after a strong close
3. Reclaim of a key level after an intraday washout

### Short-Term Buy Price

Before picking a short-term buy price, decide which setup type fits best:

- `突破型`: price is near the recent `5-10` day high and turnover is expanding
- `回踩型`: price pulled back into a recent support area but the broader `5-10` day trend is still intact
- `趋势型`: price is above key short-term averages or close clusters and still respecting support

If the stock closed strong and near the high:

- Set `触发买价` slightly above the latest completed-session close or above the latest completed-session high
- Typical breakout buffer: roughly `0.2%` to `1.0%`
- Do not force an exact price if the stock was a one-word board or effectively untradable

If the stock faded late but the broader trend is still intact:

- Set `触发买价` as a reclaim zone above the latest completed-session close
- Prefer a range rather than a single tick when liquidity is high and price swings are wide

If the stock is only suitable on pullback:

- Set `触发买价` near the latest completed-session close to latest completed-session low support band
- Require that the response explicitly mention a time window such as `9:35-10:30`

### Short-Term Stop

Anchor `止损价` to the nearest invalidation level:

- Usually the latest completed-session low
- Or the lowest low in the recent `3-5` trading day support band
- Apply a small buffer only if needed to avoid obvious noise, usually around `0.5%` to `1.5%`

Never set a stop so wide that the short-term setup becomes a medium-term trade by accident.

### Short-Term Targets

Set `第一目标` to the nearest realistic resistance:

- Recent `3-5` day swing high
- Recent unfilled gap or failed breakout area
- A modest extension above the trigger if no nearby resistance is available

Set `第二目标` to the next resistance or stronger extension:

- Next visible swing high
- Roughly one additional resistance step above `第一目标`

### Short-Term Sell Timing

Use practical language:

- `次日冲高减仓`
- `达到第一目标先卖一半`
- `回封失败或跌破分时承接位离场`

## Medium-Term Rules

Use for roughly 2 to 12 weeks.

### Medium-Term Buy Price

Anchor `触发买价` to the latest completed-session close and the recent `20-60` day structure:

- Prefer an accumulation or pullback zone near the latest close
- If the stock just broke out, use a retest zone rather than a far-above-market chase price
- A range is usually better than a single price

Before setting the zone, classify the setup:

- `突破型`: just left a `20-60` day base
- `回踩型`: pulled back toward the breakout area or mid-base support
- `趋势型`: still walking higher with higher lows and no major breakdown

### Medium-Term Stop

Anchor `止损价` below:

- The recent `20` day swing low
- Or the obvious base support zone

This stop can be wider than a short-term stop, but it still must reflect the setup's invalidation point.

### Medium-Term Targets

Set `第一目标` to:

- The recent `20-60` day swing high
- Or the first major resistance above the breakout area

Set `第二目标` to:

- A higher structural resistance level
- Or a measured breakout extension if the trend is clean

### Medium-Term Sell Timing

Use review-based timing:

- `未来2-8周内到目标位分批兑现`
- `下一次财报前后复核`
- `若行业景气转弱则提前减仓`

## Long-Term Rules

Use for roughly 6 to 24 months.

### Long-Term Buy Price

Do not pretend a long-term trade has a tight single-tick entry.

Use:

- A staged entry zone around the latest completed-session close
- Or a valuation-aware buy band built from the recent `6-12` month structure

Before setting the zone, classify the setup:

- `趋势型`: long-term uptrend remains intact
- `震荡低吸型`: long-term thesis is valid but price is in a wider consolidation band

### Long-Term Stop

Use a wider `止损价` or a thesis-break line:

- Major structural support
- Or a clearly stated business-thesis failure condition

The stop should reflect thesis failure, not normal day-to-day volatility.

### Long-Term Targets

Set `第一目标` to a realistic re-rating level and `第二目标` to a stronger upside scenario.

Good anchors:

- Prior yearly high
- Valuation re-rating band
- Earnings growth path over the next `6-24` months

### Long-Term Sell Timing

Use review windows rather than tight trading language:

- `半年报或年报后复核`
- `分红预案兑现后复核`
- `产业逻辑变化时复核`

## When To Downgrade

Do not output exact buy, stop, or target numbers when:

- The latest completed-session data cannot be verified
- Tonghuashun endpoints conflict materially and cannot be reconciled
- The stock was effectively untradable
- Recent price structure is too chaotic to support a clean invalidation line
- The broader historical window conflicts with the apparent strength of the latest completed session

In these cases, switch to:

- Conditional trigger language
- Wider entry zones
- Clear statements of what would invalidate the idea

## Output Style

When giving exact levels:

- Keep the numbers tied to the latest completed session date
- Mention whether the entry is breakout-based, pullback-based, or staged
- Explicitly output `形态类型`, `关键支撑`, and `关键阻力`
- Compute `风险收益比` from `触发买价`, `止损价`, and `第一目标`
- Keep `止损价`, `第一目标`, and `第二目标` logically ordered
- Make sure the proposed reward is meaningfully larger than the risk unless you explicitly note a lower-quality setup
