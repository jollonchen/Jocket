from __future__ import annotations

import argparse
from src.config import load_config
from src.stock_analyzer import StockAnalyzer
from src.stock_screener import StockScreener


def main():
    parser = argparse.ArgumentParser(description='A-share stock picker with Streamlit UI, Tonghuashun, AkShare and yfinance providers.')
    sub = parser.add_subparsers(dest='cmd', required=True)

    p1 = sub.add_parser('analyze')
    p1.add_argument('--code', required=True)
    p1.add_argument('--name', default='')
    p1.add_argument('--start', default=None)
    p1.add_argument('--provider', choices=['auto', 'ths', 'akshare', 'yfinance'], default=None)

    p2 = sub.add_parser('screen')
    p2.add_argument('--mode', choices=['short', 'long', 'all'], default='all')
    p2.add_argument('--top', type=int, default=10)
    p2.add_argument('--limit', type=int, default=80)
    p2.add_argument('--start', default=None)
    p2.add_argument('--provider', choices=['auto', 'ths', 'akshare', 'yfinance'], default=None)

    args = parser.parse_args()
    config = load_config()
    if getattr(args, 'provider', None):
        config.setdefault('data', {})['provider'] = args.provider

    if args.cmd == 'analyze':
        score, hist, path = StockAnalyzer(config).analyze(args.code, name=args.name, start=args.start)
        print(f"完成：{path}")
        print(score.get('summary'))
    elif args.cmd == 'screen':
        df, path = StockScreener(config).screen(args.mode, args.top, args.limit, args.start)
        print(df[['name','code','short_score','long_score','composite_score','summary']].to_string(index=False))
        print(f"\n已保存：{path}")


if __name__ == '__main__':
    main()
