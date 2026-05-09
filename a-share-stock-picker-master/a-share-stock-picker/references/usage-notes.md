# Usage Notes

Use this file for practical response shaping.

## Default Positioning

Default to:

- `盘前选股战报`
- `观察池`
- `候选名单`
- `条件交易计划`

Prefer these over hard, context-free buy/sell touting.

## Balanced-Style Preference

If the user asks for a `均衡型` list, bias toward:

- industry leaders
- strong liquidity
- clearer disclosure/fundamental support
- lower dependence on pure rumor-driven momentum

## When To Be More Cautious

Be extra cautious when:

- the request is specifically for `明天买什么`
- exact prices cannot be freshly verified
- the market is highly sentiment-driven
- the best candidates are all thinly traded or highly extended

In those cases, keep the plan conditional and explain the skip conditions clearly.

Truthfulness comes before completeness:

- if sector, news, or policy evidence is missing, say it is missing
- do not invent a sector narrative or macro catalyst to make the idea sound cleaner
- a shorter but truthful evidence note is better than a fuller but speculative one

## Execution Preference

Prefer this execution sequence:

1. If the user did not supply tickers, run `scripts/fetch_market_universe.py 200` first
2. Use that market-wide Tonghuashun prefilter to keep only roughly `200` valuable stocks
3. Run `scripts/fetch_quotes.py` for the selected universe
4. If machine-readable Tonghuashun data is available, use it as the anchor
5. If Tonghuashun fails, keep Eastmoney/Sina as context-only fallback unless you can parse them confidently
6. Run `scripts/build_watchlist.py` on the fetched JSON to score and bucket candidates
7. Run `scripts/fetch_ths_context.py` only for the final report names instead of all `200` stocks
8. Run `scripts/indicators.py` for MA/ATR/MACD clue and volume-ratio context
9. Reuse that Tonghuashun context for catalyst clues and summaries instead of relying on a single page only
10. Run `scripts/render_report.py` on the watchlist JSON to produce the Chinese markdown output
11. Or use `scripts/run_picker.py` as the one-shot wrapper
12. Upgrade to exact price plans only after verifying freshness and structure

For the default post-close / pre-open workflow, the target output size is `5` short-term names, `5` medium-term names, and `5` long-term names when enough qualified candidates are available.

When Tonghuashun provides `更多` pages or related article/search pages, keep following them while the pages still return usable content. Do not stop at the first stock page if the later pages add notices, reports, sector news, or diagnosis context that may change the conclusion.

At the same time, do not keep everything blindly:

- retain only high-signal items that are still useful for the decision
- for news, strongly prefer recent items and discard stale items that no longer affect the setup

## Tail-Entry Preference

If the user wants a practical `T+1` short-term workflow:

1. if the user did not provide tickers, first build a Tonghuashun market-wide prefilter universe of about `200` stocks
2. during trading day `D`, refresh quotes in the final hour
3. run `scripts/fetch_intraday_snapshot.py` on the quote payload
4. run `scripts/build_tail_watchlist.py` to score names for tail entry quality
5. keep the final recommendation at `5` names
6. render the result with `scripts/render_t1_plan.py`
7. or use `scripts/run_t1_tail_trade.py` as the one-shot wrapper

The same data-acquisition and analysis standards apply in both modes:

- market-wide prefilter first when no tickers are supplied
- verified quotes and history first
- sector/industry interpretation
- recent news/announcements
- policy/macro context when it can be verified
- no invented evidence

In this mode, prefer wording such as:

- `今日尾盘建仓计划`
- `D+1卖出计划`
- `高开先兑现`
- `低开跌破隔夜止损线则保护离场`
