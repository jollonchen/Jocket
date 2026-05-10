from __future__ import annotations

from pathlib import Path
import pandas as pd
from .utils import today_str, display_code


class ReportGenerator:
    def __init__(self):
        Path('output').mkdir(exist_ok=True)

    def save_analysis_markdown(self, code: str, name: str, score: dict, hist: pd.DataFrame) -> Path:
        latest = score.get('latest', {})
        risks = score.get('risk_flags', [])
        p = Path('output') / f"analysis_{display_code(code)}_{today_str()}.md"
        close = latest.get('close', '')
        date = latest.get('date', '')
        if hasattr(date, 'date'):
            date = date.date()
        lines = [
            f"# {name or display_code(code)} {display_code(code)} 个股分析",
            '',
            f"- 数据日期：{date}",
            f"- 最新收盘价：{close}",
            f"- 短线评分：{score.get('short_score')}",
            f"- 中长线评分：{score.get('long_score')}",
            f"- 综合评分：{score.get('composite_score')}",
            '',
            '## 结论',
            score.get('summary', ''),
            '',
            '## 短线评分拆解',
        ]
        for k, v in score.get('short_parts', {}).items():
            lines.append(f"- {k}: {v}")
        lines += ['', '## 中长线评分拆解']
        for k, v in score.get('long_parts', {}).items():
            lines.append(f"- {k}: {v}")
        lines += ['', '## 风险信号']
        for r in risks:
            lines.append(f"- {r}")
        news = score.get('news') or {}
        if news:
            lines += [
                '',
                '## 公开消息参考',
                f"- 消息源：{news.get('source', 'N/A')}",
                f"- 消息热度：{news.get('heat_score', 0)}",
                f"- 摘要：{news.get('summary', '暂无摘要')}",
            ]
            for item in (news.get('items') or [])[:5]:
                lines.append(
                    f"- [{item.get('kind', '消息')}] 关联度 {item.get('relevance_score', 0)}/100："
                    f"{item.get('title', '')}（{item.get('relevance_reason', '暂无关联理由')}）"
                )
        if not hist.empty:
            last = hist.iloc[-1]
            support = min(hist['low'].tail(20))
            resistance = max(hist['high'].tail(20))
            lines += [
                '', '## 关键观察位',
                f"- 20日低点参考支撑：{support:.2f}",
                f"- 20日高点参考压力：{resistance:.2f}",
                f"- MA20：{last.get('ma20', float('nan')):.2f}",
                f"- MA60：{last.get('ma60', float('nan')):.2f}",
            ]
        lines += ['', '> 本报告仅为量化研究辅助，不构成投资建议。']
        p.write_text('\n'.join(lines), encoding='utf-8')
        return p

    def save_screen_csv(self, df: pd.DataFrame, mode: str) -> Path:
        p = Path('output') / f"screen_{mode}_{today_str()}.csv"
        df.to_csv(p, index=False, encoding='utf-8-sig')
        return p
