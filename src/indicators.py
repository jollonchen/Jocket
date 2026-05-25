from __future__ import annotations

import numpy as np
import pandas as pd


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy().sort_values('date')
    for n in [5, 10, 20, 60, 120, 250]:
        df[f'ma{n}'] = df['close'].rolling(n).mean()
        df[f'vol_ma{n}'] = df['volume'].rolling(n).mean() if 'volume' in df else np.nan

    df['ret_1d'] = df['close'].pct_change()
    for n in [5, 10, 20, 60, 120]:
        df[f'ret_{n}d'] = df['close'].pct_change(n)

    delta = df['close'].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df['rsi14'] = 100 - 100 / (1 + rs)

    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd_diff'] = ema12 - ema26
    df['macd_dea'] = df['macd_diff'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = (df['macd_diff'] - df['macd_dea']) * 2

    df['boll_mid'] = df['close'].rolling(20).mean()
    boll_std = df['close'].rolling(20).std()
    df['boll_upper'] = df['boll_mid'] + 2 * boll_std
    df['boll_lower'] = df['boll_mid'] - 2 * boll_std

    low9 = df['low'].rolling(9).min()
    high9 = df['high'].rolling(9).max()
    rsv = (df['close'] - low9) / (high9 - low9).replace(0, np.nan) * 100
    df['kdj_k'] = rsv.ewm(com=2, adjust=False).mean()
    df['kdj_d'] = df['kdj_k'].ewm(com=2, adjust=False).mean()
    df['kdj_j'] = 3 * df['kdj_k'] - 2 * df['kdj_d']

    df['vol_ratio_5'] = df['volume'] / df['vol_ma5'].replace(0, np.nan)
    df['vol_ratio_20'] = df['volume'] / df['vol_ma20'].replace(0, np.nan)
    df['drawdown_60'] = df['close'] / df['close'].rolling(60).max() - 1
    df['amplitude'] = (df['high'] - df['low']) / df['close'].replace(0, np.nan)

    prev_close = df['close'].shift(1)
    true_range = pd.concat(
        [
            df['high'] - df['low'],
            (df['high'] - prev_close).abs(),
            (df['low'] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df['atr14'] = true_range.rolling(14).mean()
    return df
