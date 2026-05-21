import sys
import os
import pandas as pd
from datetime import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.market_sentiment import MarketSentimentAnalyzer

def main():
    print(f"[{datetime.now()}] Starting market sentiment cache update...")
    analyzer = MarketSentimentAnalyzer()
    
    # We want to backfill up to 60 days so that all windows (14/30/60) are fast.
    today = datetime.now()
    
    # To avoid API rate limits, we'll just run it. The module handles caching itself.
    try:
        print(f"[{datetime.now()}] Fetching and caching data for the last 60 days...")
        analyzer.analyze(trade_date=today, window_days=60, force_refresh=True, backfill_history=True)
        print(f"[{datetime.now()}] Successfully updated market sentiment cache.")
    except Exception as e:
        print(f"[{datetime.now()}] Error updating cache: {e}")

if __name__ == "__main__":
    main()
