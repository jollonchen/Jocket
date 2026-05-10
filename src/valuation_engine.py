from __future__ import annotations

import math

import pandas as pd


def _num(value):
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _latest(df: pd.DataFrame, column: str):
    if df is None or df.empty or column not in df.columns:
        return None
    series = df[column].dropna()
    if series.empty:
        return None
    return _num(series.iloc[0])


def _score_threshold(value, rules, missing_score=None):
    value = _num(value)
    if value is None:
        return missing_score
    for predicate, score in rules:
        if predicate(value):
            return score
    return missing_score


class ValuationEngine:
    def __init__(self, assumptions: dict | None = None):
        self.assumptions = {
            "years": 5,
            "cashflow_growth": 0.05,
            "terminal_growth": 0.02,
            "discount_rate": 0.10,
            "margin_of_safety": 0.20,
        }
        if assumptions:
            self.assumptions.update(assumptions)

    def analyze(self, payload: dict) -> dict:
        profile = payload.get("profile", {})
        annual = payload.get("annual", pd.DataFrame())
        source = payload.get("valuation_source", {})
        latest_price = _num(profile.get("latest_price")) or _num(source.get("currentPrice"))
        market_cap = _num(profile.get("market_cap")) or _num(source.get("marketCap"))
        shares = _num(profile.get("shares_outstanding")) or _num(source.get("sharesOutstanding"))
        revenue = _latest(annual, "totalRevenue") or _num(source.get("totalRevenue"))
        net_income = _latest(annual, "netIncome")
        equity = _latest(annual, "totalStockholderEquity")
        assets = _latest(annual, "totalAssets")
        liabilities = _latest(annual, "totalLiab")
        eps = _latest(annual, "eps")
        bvps = _latest(annual, "bvps")
        ocf = _latest(annual, "operatingCashFlow")
        fcf = _latest(annual, "freeCashFlow")
        gross_margin = _latest(annual, "grossMargin")
        net_margin = _latest(annual, "netMargin")

        pe = _num(source.get("trailingPE"))
        if pe is None:
            if market_cap and net_income and net_income > 0:
                pe = market_cap / net_income
            elif latest_price and eps and eps > 0:
                pe = latest_price / eps

        pb = _num(source.get("priceToBook"))
        if pb is None:
            if market_cap and equity and equity > 0:
                pb = market_cap / equity
            elif latest_price and bvps and bvps > 0:
                pb = latest_price / bvps

        ps = _num(source.get("priceToSalesTrailing12Months"))
        if ps is None and market_cap and revenue and revenue > 0:
            ps = market_cap / revenue

        roe = _num(source.get("returnOnEquity"))
        if roe is None and net_income and equity:
            roe = net_income / equity
        roa = _num(source.get("returnOnAssets"))
        if roa is None and net_income and assets:
            roa = net_income / assets
        de = _num(source.get("debtToEquity"))
        if de is not None and de > 3:
            de = de / 100
        if de is None and liabilities and equity:
            de = liabilities / equity

        dividend_yield = _num(source.get("dividendYield"))
        if dividend_yield is not None and dividend_yield > 0.2:
            dividend_yield = dividend_yield / 100

        dcf = self._dcf(fcf or ocf, shares, latest_price)
        debt_to_assets = liabilities / assets if liabilities and assets else None
        cashflow_quality = ocf / net_income if ocf is not None and net_income not in (None, 0) else None
        metrics = {
            "market_cap": market_cap,
            "pe_ttm": pe,
            "pe_static": market_cap / net_income if market_cap and net_income and net_income > 0 else None,
            "pb": pb,
            "ps": ps,
            "dividend_yield": dividend_yield,
            "eps": eps,
            "bvps": bvps,
            "roe": roe,
            "roa": roa,
            "debt_to_equity": de,
            "debt_to_assets": debt_to_assets,
            "gross_margin": gross_margin,
            "net_margin": net_margin,
            "cashflow_quality": cashflow_quality,
            "ev_ebitda": None,
            "dcf": dcf,
        }
        rating = self._ratings(metrics, annual)
        return {
            "metrics": metrics,
            "ratings": rating,
            "assumptions": self.assumptions,
            "limitations": self._limitations(metrics, payload),
        }

    def _dcf(self, cashflow, shares, current_price) -> dict:
        cashflow = _num(cashflow)
        shares = _num(shares)
        current_price = _num(current_price)
        if cashflow is None or shares is None or shares <= 0:
            return {"available": False, "reason": "当前数据源缺少现金流数据，暂无法计算 DCF。"}
        years = int(self.assumptions["years"])
        growth = float(self.assumptions["cashflow_growth"])
        terminal_growth = float(self.assumptions["terminal_growth"])
        discount = float(self.assumptions["discount_rate"])
        margin = float(self.assumptions["margin_of_safety"])
        if discount <= terminal_growth:
            return {"available": False, "reason": "折现率必须高于永续增长率。"}
        pv = 0
        cf = cashflow
        for year in range(1, years + 1):
            cf *= (1 + growth)
            pv += cf / ((1 + discount) ** year)
        terminal_value = cf * (1 + terminal_growth) / (discount - terminal_growth)
        pv_terminal = terminal_value / ((1 + discount) ** years)
        equity_value = pv + pv_terminal
        intrinsic_per_share = equity_value / shares
        margin_price = intrinsic_per_share * (1 - margin)
        discount_pct = (intrinsic_per_share / current_price - 1) if current_price else None
        return {
            "available": True,
            "cashflow_base": cashflow,
            "equity_value": equity_value,
            "intrinsic_per_share": intrinsic_per_share,
            "margin_price": margin_price,
            "current_price": current_price,
            "discount_pct": discount_pct,
            "label": "简化DCF估算",
        }

    def _growth(self, df: pd.DataFrame, column: str):
        if df is None or len(df) < 2 or column not in df.columns:
            return None
        current = _num(df[column].iloc[0])
        previous = _num(df[column].iloc[1])
        if current is None or previous in (None, 0):
            return None
        return current / previous - 1

    def _ratings(self, metrics: dict, annual: pd.DataFrame) -> dict:
        dcf = metrics.get("dcf", {})
        dcf_score = None
        if dcf.get("available") and dcf.get("discount_pct") is not None:
            discount = dcf["discount_pct"]
            if discount >= 0.30:
                dcf_score = 5
            elif discount >= 0.10:
                dcf_score = 4
            elif discount >= -0.10:
                dcf_score = 3
            elif discount >= -0.30:
                dcf_score = 2
            else:
                dcf_score = 1
        scores = {
            "DCF": dcf_score,
            "ROE": _score_threshold(metrics.get("roe"), [
                (lambda x: x > 0.20, 5), (lambda x: x >= 0.15, 4), (lambda x: x >= 0.10, 3), (lambda x: x >= 0.05, 2), (lambda x: True, 1)
            ]),
            "ROA": _score_threshold(metrics.get("roa"), [
                (lambda x: x > 0.10, 5), (lambda x: x >= 0.07, 4), (lambda x: x >= 0.04, 3), (lambda x: x >= 0.01, 2), (lambda x: True, 1)
            ]),
            "Gross Margin": _score_threshold(metrics.get("gross_margin"), [
                (lambda x: x >= 0.35, 5), (lambda x: x >= 0.25, 4), (lambda x: x >= 0.15, 3), (lambda x: x >= 0.08, 2), (lambda x: True, 1)
            ]),
            "Net Margin": _score_threshold(metrics.get("net_margin"), [
                (lambda x: x >= 0.18, 5), (lambda x: x >= 0.12, 4), (lambda x: x >= 0.06, 3), (lambda x: x >= 0.02, 2), (lambda x: True, 1)
            ]),
            "D/E": _score_threshold(metrics.get("debt_to_equity"), [
                (lambda x: x < 0.5, 5), (lambda x: x < 1.0, 4), (lambda x: x < 1.5, 3), (lambda x: x < 2.5, 2), (lambda x: True, 1)
            ]),
            "Debt Ratio": _score_threshold(metrics.get("debt_to_assets"), [
                (lambda x: x < 0.35, 5), (lambda x: x < 0.50, 4), (lambda x: x < 0.65, 3), (lambda x: x < 0.80, 2), (lambda x: True, 1)
            ]),
            "Cashflow Quality": _score_threshold(metrics.get("cashflow_quality"), [
                (lambda x: x >= 1.2, 5), (lambda x: x >= 0.9, 4), (lambda x: x >= 0.6, 3), (lambda x: x >= 0.2, 2), (lambda x: True, 1)
            ]),
            "P/E": self._pe_score(metrics.get("pe_ttm"), _latest(annual, "netIncome")),
            "P/B": _score_threshold(metrics.get("pb"), [
                (lambda x: 0.8 <= x <= 4, 4.2), (lambda x: 4 < x <= 7 or 0.4 <= x < 0.8, 3.3), (lambda x: 7 < x <= 10, 2.5), (lambda x: x > 10, 2), (lambda x: True, 2.5)
            ]),
            "P/S": _score_threshold(metrics.get("ps"), [
                (lambda x: 0 < x <= 2, 4.5), (lambda x: x <= 5, 3.5), (lambda x: x <= 10, 2.8), (lambda x: True, 2.2)
            ]),
            "Dividend Yield": _score_threshold(metrics.get("dividend_yield"), [
                (lambda x: x > 0.04, 5), (lambda x: x >= 0.03, 4), (lambda x: x >= 0.015, 3), (lambda x: x > 0, 2), (lambda x: True, 1)
            ]),
            "Revenue Growth": self._growth_score(self._growth(annual, "totalRevenue")),
            "Net Profit Growth": self._growth_score(self._growth(annual, "netIncome")),
        }
        categories = {
            "盈利能力": {"weight": 0.25, "items": ["ROE", "ROA", "Gross Margin", "Net Margin"]},
            "成长能力": {"weight": 0.20, "items": ["Revenue Growth", "Net Profit Growth"]},
            "估值合理性": {"weight": 0.20, "items": ["P/E", "P/B", "P/S", "Dividend Yield"]},
            "财务稳健性": {"weight": 0.15, "items": ["Debt Ratio", "D/E", "Cashflow Quality"]},
            "股东回报": {"weight": 0.10, "items": ["Dividend Yield"]},
            "DCF参考": {"weight": 0.10, "items": ["DCF"]},
        }
        category_scores = {}
        weighted = 0
        used_weight = 0
        used_item_count = 0
        total_item_count = 0
        for name, spec in categories.items():
            vals = [scores.get(item) for item in spec["items"] if scores.get(item) is not None]
            total_item_count += len(spec["items"])
            used_item_count += len(vals)
            if not vals:
                category_scores[name] = {"score": None, "weight": spec["weight"], "items": spec["items"]}
                continue
            category_score = sum(vals) / len(vals)
            category_scores[name] = {"score": round(category_score, 2), "weight": spec["weight"], "items": spec["items"]}
            weighted += category_score * spec["weight"]
            used_weight += spec["weight"]
        coverage = used_item_count / total_item_count if total_item_count else 0
        overall = round(weighted / used_weight, 1) if used_weight else None
        return {
            "scores": scores,
            "category_scores": category_scores,
            "coverage": round(coverage, 2),
            "overall": overall,
            "overall_100": round(overall * 20, 1) if overall is not None else None,
            "rating": "数据受限 / Limited" if coverage < 0.5 else self._letter(overall),
        }

    def _pe_score(self, pe, net_income):
        pe = _num(pe)
        if pe is None:
            return None
        if _num(net_income) is not None and net_income <= 0:
            return 1.5
        if 8 <= pe <= 30:
            return 5
        if 30 < pe <= 50 or 5 <= pe < 8:
            return 4
        if 50 < pe <= 80:
            return 3
        if pe > 80:
            return 2.2
        return 2.5

    def _growth_score(self, growth):
        growth = _num(growth)
        if growth is None:
            return None
        if growth > 0.20:
            return 5
        if growth >= 0.10:
            return 4
        if growth >= 0:
            return 3
        if growth >= -0.10:
            return 2
        return 1

    def _letter(self, overall):
        if overall is None:
            return "数据受限"
        if overall >= 4.5:
            return "A"
        if overall >= 4.0:
            return "A-"
        if overall >= 3.5:
            return "B+"
        if overall >= 3.0:
            return "B"
        if overall >= 2.5:
            return "C+"
        if overall >= 2.0:
            return "C"
        if overall >= 1.5:
            return "C-"
        return "D"

    def _limitations(self, metrics, payload) -> list[str]:
        notes = ["简化 DCF 仅基于现金流增长假设，不应作为单独买卖依据"]
        if not metrics.get("dcf", {}).get("available"):
            notes.append(metrics.get("dcf", {}).get("reason", "DCF 数据不足"))
        for key, label in [("pe_ttm", "PE"), ("pb", "PB"), ("ps", "PS"), ("roe", "ROE"), ("roa", "ROA"), ("debt_to_equity", "D/E")]:
            if metrics.get(key) is None:
                notes.append(f"{label} 当前数据源暂不支持或缺失")
        for error in payload.get("errors", []):
            if isinstance(error, dict):
                source = error.get("source", "数据源")
                interface = error.get("interface", "")
                notes.append(f"{source} {interface} 暂时不可用，已尝试使用其他数据源或缓存")
            else:
                notes.append(str(error).split("：", 1)[0] + "，已尝试使用其他数据源或缓存")
        return notes
