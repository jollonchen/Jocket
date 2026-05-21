from __future__ import annotations

import argparse
from src.config import load_config
from src.stock_analyzer import StockAnalyzer


def main():
    parser = argparse.ArgumentParser(description='Jocket A-share analysis with Streamlit UI, Tonghuashun, AkShare and yfinance providers.')
    sub = parser.add_subparsers(dest='cmd', required=True)

    p1 = sub.add_parser('analyze')
    p1.add_argument('--code', required=True)
    p1.add_argument('--name', default='')
    p1.add_argument('--start', default=None)
    p1.add_argument('--provider', choices=['auto', 'ths', 'akshare', 'yfinance'], default=None)

    args = parser.parse_args()
    config = load_config()
    if getattr(args, 'provider', None):
        config.setdefault('data', {})['provider'] = args.provider

    if args.cmd == 'analyze':
        score, hist, path = StockAnalyzer(config).analyze(args.code, name=args.name, start=args.start)
        print(f"完成：{path}")
        print(score.get('summary'))


if __name__ == '__main__':
    main()
