from __future__ import annotations

import pandas as pd

class Backtester:
    def __init__(self, config: dict | None = None):
        self.config = config or {}

    def placeholder(self) -> pd.DataFrame:
        return pd.DataFrame([{'提示': '回测模块已预留。建议先确认数据源稳定后，再做滚动选股回测。'}])
