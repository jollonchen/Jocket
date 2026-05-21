import yfinance as yf
import pandas as pd

try:
    ticker = "601138.SS"
    stock = yf.Ticker(ticker)
    df = stock.history(period="1mo")
    print("Recent Price Data for 601138.SS (工业富联):")
    print(df[['Open', 'High', 'Low', 'Close', 'Volume']].tail(10))
except Exception as e:
    print(f"Error: {e}")
