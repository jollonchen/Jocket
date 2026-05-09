#!/usr/bin/env python3
import sys

from ths_context import build_context, dumps


def main():
    if len(sys.argv) < 2:
        print("Usage: fetch_ths_context.py <ticker...>", file=sys.stderr)
        sys.exit(1)
    items = [build_context(ticker) for ticker in sys.argv[1:]]
    print(dumps(items))


if __name__ == "__main__":
    main()
