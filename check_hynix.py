import yfinance as yf
import pandas as pd

try:
    # HK ETF
    hk_etf = yf.Ticker("07709.HK")
    hk_df = hk_etf.history(period="5d")
    print("07709.HK (CSOP SK Hynix 2x) 5-day Data:")
    print(hk_df[['Open', 'High', 'Low', 'Close', 'Volume']])
    
    # Underlying SK Hynix (Korea)
    kr_stock = yf.Ticker("000660.KS")
    kr_df = kr_stock.history(period="5d")
    print("\n000660.KS (SK Hynix) 5-day Data:")
    print(kr_df[['Open', 'High', 'Low', 'Close', 'Volume']])
except Exception as e:
    print(f"Error: {e}")
