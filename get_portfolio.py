import yfinance as yf
import pandas as pd

portfolio = {
    "永鼎股份": "600105.SS",
    "生益科技": "600183.SS",
    "沪电股份": "002463.SZ",
    "立讯精密": "002475.SZ",
    "盈峰环境": "000967.SZ",
    "亨通光电": "600487.SS",
    "工业富联": "601138.SS",
    "苏州固锝": "002079.SZ",
    "新易盛": "300502.SZ",
    "天孚通信": "300394.SZ",
    "太辰光": "300570.SZ",
    "联特科技": "301205.SZ"
}

results = []
for name, ticker in portfolio.items():
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="20d")
        if not df.empty and len(df) >= 5:
            last_close = df['Close'].iloc[-1]
            prev_close = df['Close'].iloc[-2]
            change = (last_close - prev_close) / prev_close * 100
            
            ma5 = df['Close'].tail(5).mean()
            ma10 = df['Close'].tail(10).mean()
            ma20 = df['Close'].tail(20).mean()
            
            trend = "Up" if ma5 > ma10 and ma10 > ma20 else "Down" if ma5 < ma10 and ma10 < ma20 else "Consolidating"
            
            # check momentum
            max_20 = df['High'].max()
            min_20 = df['Low'].min()
            position_in_range = (last_close - min_20) / (max_20 - min_20) if max_20 > min_20 else 0
            
            results.append({
                "Name": name,
                "Ticker": ticker,
                "Last Close": round(last_close, 2),
                "Change %": round(change, 2),
                "MA5": round(ma5, 2),
                "MA10": round(ma10, 2),
                "MA20": round(ma20, 2),
                "Trend": trend,
                "Range Pos": round(position_in_range, 2)
            })
    except Exception as e:
        print(f"Error fetching {name}: {e}")

res_df = pd.DataFrame(results)
print(res_df.to_string(index=False))
