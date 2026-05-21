from __future__ import annotations

import math

import pandas as pd


def _safe(x, default=0.0):
    try:
        if pd.isna(x) or math.isinf(float(x)):
            return default
        return float(x)
    except Exception:
        return default


def _round(value, digits=2):
    try:
        return round(float(value), digits)
    except Exception:
        return value


class FactorEngine:
    def __init__(self, config: dict | None = None):
        self.config = config or {}

    def score(self, hist: pd.DataFrame) -> dict:
        if hist is None or len(hist) < 60:
            return self.empty_score('历史数据不足')

        row = hist.iloc[-1]
        prev = hist.iloc[-2] if len(hist) > 1 else row
        evidence = self._evidence(row, prev, hist)

        short_breakdown = self._short_breakdown(row, prev, hist, evidence)
        long_breakdown = self._long_breakdown(row, hist, evidence)
        short_parts = {item['dimension']: item['score'] for item in short_breakdown}
        long_parts = {item['dimension']: item['score'] for item in long_breakdown}
        short_score = min(100, max(0, round(sum(short_parts.values()), 1)))
        long_score = min(100, max(0, round(sum(long_parts.values()), 1)))
        composite_score = round(short_score * 0.6 + long_score * 0.4, 1)
        risk_flags = self._risk_flags(row, hist)
        rating, rating_explanation = self._rating(short_score, long_score, short_parts, long_parts, evidence)
        explanations = self._score_explanations(short_breakdown, long_breakdown, evidence)

        return {
            'short_score': short_score,
            'long_score': long_score,
            'composite_score': composite_score,
            'rating': rating,
            'rating_explanation': rating_explanation,
            'short_parts': short_parts,
            'long_parts': long_parts,
            'short_breakdown': short_breakdown,
            'long_breakdown': long_breakdown,
            'evidence': evidence,
            'score_explanations': explanations,
            'formula': self._formula(),
            'limitations': self._limitations(evidence),
            'risk_flags': risk_flags,
            'latest': row.to_dict(),
            'summary': self._summary(short_score, long_score, risk_flags, rating),
        }

    def empty_score(self, reason: str) -> dict:
        return {
            'short_score': 0,
            'long_score': 0,
            'composite_score': 0,
            'rating': '数据不足',
            'rating_explanation': reason,
            'short_parts': {},
            'long_parts': {},
            'short_breakdown': [],
            'long_breakdown': [],
            'evidence': {},
            'score_explanations': [],
            'formula': self._formula(),
            'limitations': ['行情历史不足，无法计算完整技术指标', '评分仅用于研究辅助，不构成投资建议'],
            'risk_flags': [reason],
            'latest': {},
            'summary': reason,
        }

    def _evidence(self, r, p, hist) -> dict:
        amount = _safe(r.get('amount_est'), _safe(r.get('amount')))
        if not amount:
            amount = _safe(r.get('close')) * _safe(r.get('volume'))
        rolling_high_20 = hist['high'].tail(20).max() if 'high' in hist else None
        rolling_amount_20 = hist['amount_est'].tail(20).mean() if 'amount_est' in hist else None
        if rolling_amount_20 is None and {'close', 'volume'}.issubset(hist.columns):
            rolling_amount_20 = (hist['close'] * hist['volume']).tail(20).mean()
        volatility_60d = hist['ret_1d'].tail(60).std() if 'ret_1d' in hist else None
        max_drawdown_60d = _safe(r.get('drawdown_60'))
        close = _safe(r.get('close'))
        ma20 = _safe(r.get('ma20'))
        return {
            'close': _round(close),
            'prev_close': _round(_safe(p.get('close'))),
            'open': _round(_safe(r.get('open'))),
            'high': _round(_safe(r.get('high'))),
            'low': _round(_safe(r.get('low'))),
            'ma5': _round(_safe(r.get('ma5'))),
            'ma10': _round(_safe(r.get('ma10'))),
            'ma20': _round(ma20),
            'ma60': _round(_safe(r.get('ma60'))),
            'ma120': _round(_safe(r.get('ma120'))),
            'ma250': _round(_safe(r.get('ma250'))),
            'return_1d': _round(_safe(r.get('ret_1d')), 4),
            'return_5d': _round(_safe(r.get('ret_5d')), 4),
            'return_20d': _round(_safe(r.get('ret_20d')), 4),
            'return_60d': _round(_safe(r.get('ret_60d')), 4),
            'return_120d': _round(_safe(r.get('ret_120d')), 4),
            'volume': _round(_safe(r.get('volume')), 0),
            'volume_ma5': _round(_safe(r.get('vol_ma5')), 0),
            'volume_ma20': _round(_safe(r.get('vol_ma20')), 0),
            'volume_ratio_5': _round(_safe(r.get('vol_ratio_5')), 2),
            'volume_ratio_20': _round(_safe(r.get('vol_ratio_20')), 2),
            'amount_est': _round(amount, 0),
            'amount_avg_20d': _round(rolling_amount_20, 0),
            'turnover_rate': _round(_safe(r.get('turnover_rate')), 2) if 'turnover_rate' in r else None,
            'rsi14': _round(_safe(r.get('rsi14')), 2),
            'macd_diff': _round(_safe(r.get('macd_diff')), 4),
            'macd_dea': _round(_safe(r.get('macd_dea')), 4),
            'macd_hist': _round(_safe(r.get('macd_hist')), 4),
            'prev_macd_hist': _round(_safe(p.get('macd_hist')), 4),
            'kdj_k': _round(_safe(r.get('kdj_k')), 2),
            'kdj_d': _round(_safe(r.get('kdj_d')), 2),
            'kdj_j': _round(_safe(r.get('kdj_j')), 2),
            'high_20d': _round(rolling_high_20),
            'distance_to_20d_high': _round(close / rolling_high_20 - 1, 4) if rolling_high_20 else None,
            'distance_to_ma20': _round(close / ma20 - 1, 4) if ma20 else None,
            'volatility_60d': _round(volatility_60d, 4),
            'max_drawdown_60d': _round(max_drawdown_60d, 4),
            'amplitude': _round(_safe(r.get('amplitude')), 4),
            'data_source': r.get('data_source', ''),
            'history_days': len(hist),
        }

    def _item(
        self,
        dimension: str,
        score: float,
        max_score: float,
        logic: str,
        data_points: dict,
        positive: list[str],
        negative: list[str],
        decision_impact: str,
    ) -> dict:
        score = round(max(0, min(max_score, score)), 1)
        return {
            'dimension': dimension,
            'score': score,
            'max_score': max_score,
            'score_rate': round(score / max_score, 3) if max_score else 0,
            'weight': round(max_score / 100, 2),
            'logic': logic,
            'data_points': data_points,
            'positive_factors': positive or ['暂无明确加分项'],
            'negative_factors': negative or ['暂无明显扣分项'],
            'decision_impact': decision_impact,
        }

    def _short_breakdown(self, r, p, hist, ev) -> list[dict]:
        close = _safe(r.get('close'))
        positive, negative = [], []
        trend = 0
        if close > _safe(r.get('ma20')):
            trend += 5; positive.append('收盘价高于 MA20，短线趋势处于均线之上')
        else:
            negative.append('收盘价低于 MA20，短线趋势未确认')
        if _safe(r.get('ma5')) > _safe(r.get('ma10')) > _safe(r.get('ma20')):
            trend += 8; positive.append('MA5 > MA10 > MA20，短期均线呈多头排列')
        else:
            negative.append('短期均线未形成 MA5 > MA10 > MA20 的多头排列')
        if close > _safe(r.get('ma60')):
            trend += 2; positive.append('收盘价高于 MA60，短中期趋势有支撑')
        if _safe(r.get('ret_20d')) > 0:
            trend += 3; positive.append('近20日收益为正，阶段趋势偏强')
        if 0 < _safe(r.get('ret_5d')) < 0.15:
            trend += 2; positive.append('近5日温和上涨，短线动量延续')
        elif _safe(r.get('ret_5d')) >= 0.15:
            trend += 1; negative.append('近5日涨幅较高，追高性价比下降')
        if _safe(r.get('ret_20d')) > 0.45:
            trend -= 5; negative.append('近20日涨幅过高，存在短线过热风险')
        trend_item = self._item(
            '趋势强度', trend, 20,
            '根据均线排列、价格位置、近期涨跌幅和距离高点判断短线趋势强弱。',
            {k: ev.get(k) for k in ['close', 'ma5', 'ma10', 'ma20', 'ma60', 'return_5d', 'return_20d', 'distance_to_20d_high']},
            positive, negative,
            '趋势分越高，越适合进入短线观察池；若涨幅过高，应等待回踩或突破确认。'
        )

        positive, negative = [], []
        vp = 0
        if _safe(r.get('ret_1d')) > 0 and _safe(r.get('vol_ratio_5')) > 1.1:
            vp += 8; positive.append('当日上涨且量比高于5日均量，属于放量上行')
        elif _safe(r.get('ret_1d')) > 0:
            vp += 3; positive.append('当日上涨，但量能确认有限')
        if _safe(r.get('vol_ratio_20')) > 1.0:
            vp += 5; positive.append('成交量高于20日均量，活跃度提升')
        else:
            negative.append('成交量未高于20日均量，量能配合一般')
        if _safe(r.get('vol_ratio_20')) > 1.8 and _safe(r.get('ret_1d')) > 0:
            vp += 5; positive.append('显著放量上涨，资金关注度较高')
        if _safe(r.get('vol_ratio_20')) > 2.5 and abs(_safe(r.get('ret_1d'))) < 0.01:
            vp -= 5; negative.append('高量但涨幅有限，可能存在分歧或滞涨')
        if _safe(r.get('vol_ratio_20')) > 1.5 and _safe(r.get('ret_1d')) < 0:
            vp -= 4; negative.append('放量下跌，短线承接需要观察')
        vp_item = self._item(
            '量价配合', vp, 20,
            '根据当日涨跌、成交量相对均量、放量上涨/滞涨/下跌判断量价是否健康。',
            {k: ev.get(k) for k in ['return_1d', 'volume', 'volume_ma5', 'volume_ma20', 'volume_ratio_5', 'volume_ratio_20', 'amount_est']},
            positive, negative,
            '量价配合强说明交易关注度提升；若放量但价格不涨，应降低追涨意愿。'
        )

        positive, negative = [], []
        mom = 0
        rsi = _safe(r.get('rsi14'))
        if 50 <= rsi <= 70:
            mom += 5; positive.append('RSI 位于 50-70，动量偏强且未明显过热')
        elif 45 <= rsi < 50:
            mom += 3; positive.append('RSI 接近强弱分界，动量处于修复区')
        elif rsi > 80:
            mom -= 5; negative.append('RSI 高于 80，短线过热风险上升')
        if _safe(r.get('macd_diff')) > _safe(r.get('macd_dea')):
            mom += 5; positive.append('MACD DIF 高于 DEA，动量结构偏多')
        else:
            negative.append('MACD DIF 未高于 DEA，趋势动量不足')
        if _safe(r.get('macd_hist')) > _safe(p.get('macd_hist')):
            mom += 3; positive.append('MACD 柱体扩大，短线动量增强')
        else:
            negative.append('MACD 柱体未继续扩大')
        if _safe(r.get('kdj_k')) > _safe(r.get('kdj_d')):
            mom += 2; positive.append('KDJ K 值高于 D 值，短线摆动指标偏强')
        else:
            negative.append('KDJ 未形成偏强结构')
        mom_item = self._item(
            '动量指标', mom, 15,
            '综合 RSI、MACD、KDJ 判断短线动量强弱和是否过热。',
            {k: ev.get(k) for k in ['rsi14', 'macd_diff', 'macd_dea', 'macd_hist', 'prev_macd_hist', 'kdj_k', 'kdj_d', 'kdj_j']},
            positive, negative,
            '动量分高说明趋势正在获得技术指标确认；若 RSI 过热，则高分也不等于适合追高。'
        )

        positive, negative = [], []
        liq = 0
        amount = _safe(ev.get('amount_est'))
        if amount > 50_000_000:
            liq += 5; positive.append('成交额高于5000万，具备基础交易活跃度')
        else:
            negative.append('成交额低于5000万，短线流动性不足')
        if amount > 150_000_000:
            liq += 5; positive.append('成交额高于1.5亿，买卖执行更容易')
        if amount > 500_000_000:
            liq += 5; positive.append('成交额高于5亿，短线承载能力较强')
        if ev.get('turnover_rate') is None:
            negative.append('换手率暂未取得，流动性判断仍需用成交额和成交量补充验证')
        liq_item = self._item(
            '流动性', liq, 15,
            '根据成交额、成交量和换手率可用性判断短线交易执行难度。',
            {k: ev.get(k) for k in ['amount_est', 'amount_avg_20d', 'volume', 'turnover_rate']},
            positive, negative,
            '流动性分高说明短线进出更顺畅；低流动性标的不适合激进短线。'
        )

        positive, negative = [], []
        sector_proxy = 0
        if _safe(r.get('ret_20d')) > 0:
            sector_proxy += 5; positive.append('近20日动量为正，作为题材活跃度代理加分')
        if _safe(r.get('ret_60d')) > 0:
            sector_proxy += 5; positive.append('近60日动量为正，说明阶段相对强度尚可')
        if _safe(r.get('ret_5d')) > _safe(r.get('ret_20d')) / 4:
            sector_proxy += 5; positive.append('近5日表现相对20日动量不弱，短期活跃度仍在')
        negative.append('当前版本尚未接入行业涨幅排名、概念热度、涨停家数、新闻热度和资金流向')
        sector_item = self._item(
            '行业/题材代理', sector_proxy, 15,
            '本项使用价格动量和市场活跃度作为行业/题材热度代理；UI 基本面模块可补充行业归属和 Sector。',
            {k: ev.get(k) for k in ['return_5d', 'return_20d', 'return_60d', 'volume_ratio_20']},
            positive, negative,
            '该分数只能表示“价格活跃度代理”，不能替代行业涨幅、概念热度和资金流判断。'
        )

        positive, negative = [], []
        risk = 15
        if _safe(r.get('ret_5d')) > 0.25:
            risk -= 5; negative.append('近5日涨幅过大，回撤压力上升')
        else:
            positive.append('近5日涨幅未达到极端过热阈值')
        if _safe(r.get('drawdown_60')) > -0.03 and _safe(r.get('ret_20d')) > 0.25:
            risk -= 4; negative.append('接近60日高位且20日涨幅较大，追高风险上升')
        if _safe(r.get('amplitude')) > 0.08:
            risk -= 3; negative.append('当日振幅较高，短线波动风险偏大')
        else:
            positive.append('当日振幅未触发高波动扣分')
        if close < _safe(r.get('ma20')):
            risk -= 6; negative.append('收盘价低于 MA20，风控得分扣分')
        else:
            positive.append('收盘价位于 MA20 上方，短线风控结构较好')
        risk_item = self._item(
            '风险控制', risk, 15,
            '风险控制分越高，代表当前技术风险越低；分数越低，代表追高、回撤或波动风险越大。',
            {k: ev.get(k) for k in ['return_5d', 'return_20d', 'distance_to_ma20', 'max_drawdown_60d', 'amplitude', 'rsi14']},
            positive, negative,
            '风控分低时，即使趋势分较高，也应转为谨慎观察，避免无条件追高。'
        )
        return [trend_item, vp_item, mom_item, liq_item, sector_item, risk_item]

    def _long_breakdown(self, r, hist, ev) -> list[dict]:
        quality = self._item(
            '质量初筛', 10, 15,
            '财务质量数据不足时按中性偏保守口径处理，避免错误放大未知基本面优势。',
            {'roe': '暂未获取', '毛利率': '暂未获取', '经营现金流': '暂未获取'},
            ['财务质量按中性偏保守口径处理，等待后续基本面模块校准'],
            ['ROE、毛利率、经营现金流不足，不作为独立基本面结论'],
            '中长线质量判断数据受限，需要补充财报和现金流数据。'
        )
        growth = self._item(
            '成长初筛', 8, 15,
            '成长数据不足时按保守口径处理，避免把未知成长误判为优势。',
            {'营收同比': '暂未获取', '净利润同比': '暂未获取', '扣非净利润': '暂未获取'},
            ['成长项按中性偏保守口径处理'],
            ['缺少成长数据，不能据此判断业绩趋势'],
            '成长性需要结合财报、公告和行业景气度进一步验证。'
        )
        valuation = self._item(
            '估值初筛', 5, 10,
            '估值数据不足时按中性口径处理，正式结论需要结合 PE/PB/PS 与现金流估算。',
            {'PE': '暂未获取', 'PB': '暂未获取', 'PS': '暂未获取'},
            ['估值项按中性口径处理'],
            ['缺少估值分位，不能判断便宜或昂贵'],
            '估值结论需要接入估值指标和历史分位后才能成立。'
        )

        positive, negative = [], []
        close = _safe(r.get('close'))
        long_trend = 0
        if close > _safe(r.get('ma60')):
            long_trend += 8; positive.append('收盘价高于 MA60，中期趋势偏强')
        else:
            negative.append('收盘价低于 MA60，中期趋势未确认')
        if close > _safe(r.get('ma120')):
            long_trend += 8; positive.append('收盘价高于 MA120，长期趋势结构改善')
        else:
            negative.append('收盘价低于 MA120，长期趋势仍需确认')
        if close > _safe(r.get('ma250')):
            long_trend += 5; positive.append('收盘价高于 MA250，年线结构偏强')
        else:
            negative.append('收盘价未站上 MA250，长期趋势证据不足')
        if _safe(r.get('ma60')) > _safe(r.get('ma120')):
            long_trend += 6; positive.append('MA60 高于 MA120，中长期均线方向偏多')
        else:
            negative.append('MA60 未高于 MA120，中长期均线未完全转强')
        if _safe(r.get('ret_120d')) > 0:
            long_trend += 5; positive.append('近120日收益为正，阶段趋势向上')
        else:
            negative.append('近120日收益未转正或历史不足')
        if _safe(r.get('drawdown_60')) > -0.18:
            long_trend += 3; positive.append('近60日回撤控制尚可')
        long_trend_item = self._item(
            '长期趋势', long_trend, 35,
            '根据 MA60/MA120/MA250、均线方向、近60/120日涨跌幅和回撤控制判断中长期价格结构。',
            {k: ev.get(k) for k in ['close', 'ma60', 'ma120', 'ma250', 'return_60d', 'return_120d', 'max_drawdown_60d']},
            positive, negative,
            '长期趋势分高可进入中长期研究池，但仍需财务、估值和行业逻辑验证。'
        )

        positive, negative = [], []
        stability = 0
        vol = _safe(ev.get('volatility_60d'))
        dd = _safe(ev.get('max_drawdown_60d'))
        if vol < 0.025:
            stability += 5; positive.append('近60日波动率较低，走势相对稳定')
        elif vol < 0.04:
            stability += 3; positive.append('近60日波动率处于可接受区间')
        else:
            negative.append('近60日波动率偏高')
        if dd > -0.12:
            stability += 5; positive.append('近60日最大回撤较小')
        elif dd > -0.20:
            stability += 3; positive.append('近60日回撤尚可控')
        else:
            negative.append('近60日回撤较大')
        stability_item = self._item(
            '波动稳定性', stability, 10,
            '根据近60日波动率、最大回撤和价格偏离程度评估中长期持有体验。',
            {k: ev.get(k) for k in ['volatility_60d', 'max_drawdown_60d', 'distance_to_ma20']},
            positive, negative,
            '稳定性越高，中长期跟踪体验越平滑；高波动标的需要更严格仓位控制。'
        )

        positive, negative = [], []
        risk = 15
        if close < _safe(r.get('ma120')):
            risk -= 4; negative.append('收盘价低于 MA120，长期趋势破位风险较高')
        else:
            positive.append('收盘价高于 MA120，长期趋势风险较低')
        if _safe(r.get('ret_120d')) < -0.25:
            risk -= 4; negative.append('近120日跌幅较大，中长期弱势风险仍在')
        if _safe(ev.get('volatility_60d')) > 0.045:
            risk -= 3; negative.append('近60日波动率偏高')
        if _safe(r.get('ret_20d')) > 0.35:
            risk -= 2; negative.append('近20日涨幅过快，中长期建仓位置可能偏高')
        if ev.get('history_days', 0) < 120:
            risk -= 2; negative.append('历史样本少于120个交易日，长期判断数据受限')
        risk_item = self._item(
            '风险控制', risk, 15,
            '根据长期趋势破位、回撤、高波动、短期涨幅过大和数据完整性评估中长期风险。',
            {k: ev.get(k) for k in ['return_20d', 'return_120d', 'volatility_60d', 'max_drawdown_60d', 'history_days']},
            positive, negative,
            '中长期风控分低时，应降低研究优先级，并等待趋势或基本面确认。'
        )
        return [quality, growth, valuation, long_trend_item, stability_item, risk_item]

    def _risk_flags(self, r, hist) -> list[str]:
        flags = []
        if _safe(r.get('rsi14')) > 82:
            flags.append('RSI 过热，短线追高风险较高')
        if _safe(r.get('ret_5d')) > 0.25:
            flags.append('近5日涨幅过大，可能存在回撤压力')
        if _safe(r.get('close')) < _safe(r.get('ma20')):
            flags.append('收盘价低于 MA20，短线趋势未确认')
        if _safe(r.get('vol_ratio_20')) > 2.5 and _safe(r.get('ret_1d')) <= 0:
            flags.append('放量但价格未上涨，注意出货/分歧')
        min_days = int(self.config.get('market', {}).get('min_history_days', 120))
        if len(hist) < min_days:
            flags.append(f'历史数据不足{min_days}个交易日，模型稳定性较弱')
        return flags or ['未发现明显模型内风险信号']

    def _rating(self, short_score, long_score, short_parts, long_parts, ev) -> tuple[str, str]:
        data_limited = ev.get('history_days', 0) < 120
        suffix = '（数据受限）' if data_limited else ''
        risk_score = short_parts.get('风险控制', 0)
        long_trend = long_parts.get('长期趋势', 0)
        if short_score >= 80 and risk_score >= 10:
            rating = '短线强势观察'
            explanation = '短线趋势和量价信号较强，适合优先观察，但仍需结合买入位置、止损和市场环境。'
        elif short_score >= 70 and risk_score < 10:
            rating = '短线偏强但风险较高'
            explanation = '短线信号偏强，但风险控制项扣分较多，适合谨慎观察，不宜无条件追高。'
        elif long_score >= 75 and long_trend >= 24:
            rating = '中长期研究池'
            explanation = '中长期价格结构较好，但当前版本财务和估值数据受限，需要进一步基本面验证。'
        elif short_score < 55 and long_score < 55:
            rating = '暂不优先关注'
            explanation = '短线和中长线信号均不突出，除非有外部催化，否则不建议作为优先研究标的。'
        elif short_score >= 70:
            rating = '谨慎观察'
            explanation = '短线有一定强度，但需要等待回踩、突破确认或量能延续。'
        else:
            rating = '中性观察'
            explanation = '当前信号不极端，适合继续跟踪并等待更明确的趋势或基本面证据。'
        return rating + suffix, explanation

    def _score_explanations(self, short_breakdown, long_breakdown, ev) -> list[str]:
        all_items = short_breakdown + long_breakdown
        top = sorted(all_items, key=lambda x: x['score_rate'], reverse=True)[:3]
        weak = sorted(all_items, key=lambda x: x['score_rate'])[:3]
        return [
            '短线高分主要来自趋势、量价、动量、流动性和风险控制的综合表现；高分代表信号强度，不代表确定收益。',
            '中长线评分会优先纳入财务质量、成长、估值与股息；相关数据不足时按保守研究口径处理。',
            '贡献较大的维度：' + '、'.join(f"{item['dimension']}({item['score']}/{item['max_score']})" for item in top),
            '拖累较大的维度：' + '、'.join(f"{item['dimension']}({item['score']}/{item['max_score']})" for item in weak),
            f"当前更接近{'趋势机会' if ev.get('close', 0) > ev.get('ma20', 0) else '震荡/修复机会'}，仍需结合公告、行业热度、资金流和大盘环境验证。",
        ]

    def _limitations(self, ev) -> list[str]:
        notes = [
            '财务/估值数据不足时，质量、成长、估值会按保守口径处理；取得有效数据后会自动纳入评分',
            '行业热度、概念强度和主力资金流尚未接入评分，行业名称或 Sector 不等同于行业热度',
            '评分仅用于研究辅助，不构成投资建议',
        ]
        if ev.get('history_days', 0) < 120:
            notes.insert(0, '中长期评分的历史样本少于120个交易日，长期判断数据受限')
        return notes

    def _formula(self) -> dict:
        return {
            'short': {
                '趋势强度': ['close > MA20 +5', 'MA5 > MA10 > MA20 +8', 'close > MA60 +2', '近20日收益为正 +3', '近5日温和上涨 +2', '近20日涨幅过高 -5'],
                '量价配合': ['上涨且高于5日均量 +8', '成交量高于20日均量 +5', '显著放量上涨 +5', '高量滞涨 -5', '放量下跌 -4'],
                '动量指标': ['RSI 50-70 +5', 'MACD DIF > DEA +5', 'MACD柱体扩大 +3', 'KDJ K > D +2', 'RSI > 80 -5'],
                '流动性': ['成交额 > 5000万 +5', '成交额 > 1.5亿 +5', '成交额 > 5亿 +5'],
                '行业/题材代理': ['近20日动量为正 +5', '近60日动量为正 +5', '近5日活跃度相对不弱 +5'],
                '风险控制': ['基础15分', '近5日涨幅过大 -5', '高位且20日涨幅大 -4', '当日振幅过高 -3', '跌破MA20 -6'],
            },
            'long': {
                '质量初筛': ['ROE、毛利率、经营现金流不足时，按保守分10/15处理'],
                '成长初筛': ['营收/利润增速不足时，按保守分8/15处理'],
                '估值初筛': ['PE/PB/PS不足时，按中性分5/10处理'],
                '长期趋势': ['close > MA60 +8', 'close > MA120 +8', 'close > MA250 +5', 'MA60 > MA120 +6', '近120日收益为正 +5', '回撤控制尚可 +3'],
                '波动稳定性': ['近60日低波动 +5', '近60日回撤较小 +5'],
                '风险控制': ['基础15分', '跌破MA120 -4', '近120日跌幅较大 -4', '高波动 -3', '近20日涨幅过快 -2', '历史样本不足 -2'],
            },
        }

    def _summary(self, short_score, long_score, risks, rating) -> str:
        if short_score >= 85:
            base = '短线强势，但需检查是否追高；适合优先观察，不等于直接买入。'
        elif short_score >= 70:
            base = '短线偏强，可进入观察池，等待回踩或确认信号。'
        elif short_score >= 55:
            base = '短线中性偏弱，仅适合继续跟踪，不作为优先标的。'
        elif short_score >= 40:
            base = '短线信号不足，除非有外部催化，否则不建议优先关注。'
        else:
            base = '短线弱势或风险较高，建议回避。'
        return f'{rating}。{base} 风险提示：' + '；'.join(risks[:2])
