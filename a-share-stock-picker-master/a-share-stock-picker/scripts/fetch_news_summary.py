#!/usr/bin/env python3
import json
import sys

from ths_context import build_context


def main():
    if len(sys.argv) < 2:
        print('Usage: fetch_news_summary.py <ticker...>', file=sys.stderr)
        sys.exit(1)
    out = []
    for ticker in sys.argv[1:]:
        context = build_context(ticker)
        out.append(
            {
                'ticker': context['ticker'],
                'summary': context.get('summary'),
                'highlights': context.get('sectionHighlights', [])[:6],
                'pageCount': context.get('pageCount', 0),
                'paginatedPageCount': context.get('paginatedPageCount', 0),
                'usefulItemCount': context.get('usefulItemCount', 0),
                'errors': context.get('errors', []),
            }
        )
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
