from datetime import datetime, timedelta
from typing import List, Dict, Optional
import akshare as ak
import pandas as pd
import re
import sqlite3
from requests.exceptions import RequestException
from loguru import logger
from .database_manager import DatabaseManager
import os
from contextlib import contextmanager

@contextmanager
def temporary_no_proxy():
    """Context manager to temporarily unset proxy environment variables."""
    proxies = {k: os.environ.get(k) for k in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']}
    for k in proxies:
        if k in os.environ:
            del os.environ[k]
    try:
        yield
    finally:
        for k, v in proxies.items():
            if v is not None:
                os.environ[k] = v

class StockTools:
    """金融分析股票工具 - 结合高性能数据库缓存与增量更新"""

    def __init__(self, db: DatabaseManager, auto_update: bool = True):
        """
        初始化股票工具

        Args:
            db: 数据库管理器
            auto_update: 是否在列表为空时自动更新，默认 True
        """
        self.db = db
        if auto_update:
            self._check_and_update_stock_list()

    def _check_and_update_stock_list(self, force: bool = False):
        """检查并更新股票列表。仅在列表为空或 force=True 时从网络拉取。"""
        # 直接查询表中记录数
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM stock_list")
        count = cursor.fetchone()[0]

        if count > 0 and not force:
            logger.info(f"ℹ️ Stock list already cached ({count} stocks)")
            return

        logger.info("📡 Updating A-share and HK-share stock list from akshare...")

        def fetch_data():
            # A-share
            df_a = ak.stock_zh_a_spot_em()
            df_a = df_a[['代码', '名称']].copy()
            df_a.columns = ['code', 'name']

            # HK-share
            df_hk = ak.stock_hk_spot_em()
            df_hk = df_hk[['代码', '名称']].copy()
            df_hk.columns = ['code', 'name']

            # Combine
            return pd.concat([df_a, df_hk], ignore_index=True)

        try:
            try:
                df_combined = fetch_data()
            except (RequestException, Exception) as e:
                if "Proxy" in str(e) or "proxy" in str(e):
                    logger.warning(f"⚠️ Proxy error detected: {e}. Retrying with proxy disabled...")
                    with temporary_no_proxy():
                        df_combined = fetch_data()
                else:
                    raise e

            self.db.save_stock_list(df_combined)
            logger.info(f"✅ Cached {len(df_combined)} stocks (A-share + HK) to database.")

        except Exception as e:
            logger.error(f"❌ Failed to sync stock list: {e}")


    def search_ticker(self, query: str, limit: int = 5) -> List[Dict]:
        """
        模糊搜索 A 股股票代码或名称，支持常见缩写。
        """
        # 清洗后缀 (如 CATL.SZ -> CATL, 000001.SZ -> 000001)
        clean_query = re.sub(r'\.(SZ|SH|HK|US)$', '', query, flags=re.IGNORECASE)

        # 常见缩写映射
        aliases = {
            "CATL": "宁德时代",
            "BYD": "比亚迪",
            "TSLA": "特斯拉",
            "Moutai": "贵州茅台",
            "Tencent": "腾讯",
            "Alibaba": "阿里巴巴",
            "Meituan": "美团",
        }

        search_query = aliases.get(clean_query.upper(), clean_query)

        # Robustness: if regex-like ticker code is embedded in query (e.g. "300364 中文在线"), try to extract it
        if not search_query.isdigit():
             # Extract explicit 5-6 digit codes
             match = re.search(r'\b(\d{5,6})\b', clean_query)
             if match:
                 search_query = match.group(1)

        return self.db.search_stock(search_query, limit)

    def get_stock_price(
        self,
        ticker: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        force_sync: bool = False,
    ) -> pd.DataFrame:
        """
        获取指定股票的历史价格数据。优先从本地缓存读取，缺失时自动从网络补齐。

        Args:
            ticker: 股票代码，如 "600519"（贵州茅台）或 "000001"（平安银行）。
            start_date: 开始日期，格式 "YYYY-MM-DD"。默认为 90 天前。
            end_date: 结束日期，格式 "YYYY-MM-DD"。默认为今天。

        Returns:
            包含 date, open, close, high, low, volume, change_pct 列的 DataFrame。
        """
        now = datetime.now()
        if not end_date:
            end_date = now.strftime('%Y-%m-%d')
        if not start_date:
            start_date = (now - timedelta(days=90)).strftime('%Y-%m-%d')

        df_db = self.db.get_stock_prices(ticker, start_date, end_date)

        need_update = False
        if df_db.empty:
            need_update = True
        else:
            db_latest = pd.to_datetime(df_db['date'].max())
            req_latest = pd.to_datetime(end_date)
            if (req_latest - db_latest).days > 2:
                need_update = True

        if force_sync:
            need_update = True

        if need_update:
            logger.info(f"📡 Data stale or missing for {ticker}, syncing from network...")

            # 清洗 ticker，确保只包含数字（Akshare A 股接口通常只需要数字代码）
            clean_ticker = "".join(filter(str.isdigit, ticker))
            if not clean_ticker:
                # Non A/H numeric tickers are not supported by the current data source.
                logger.warning(f"⚠️ Unsupported ticker format (A/H only): {ticker}")
                return df_db

            try:
                s_fmt = start_date.replace("-", "")
                e_fmt = end_date.replace("-", "")

                df_remote = None

                def fetch_data():
                    if len(clean_ticker) == 5:
                        # HK Stock
                        return ak.stock_hk_hist(
                            symbol=clean_ticker, period="daily",
                            start_date=s_fmt, end_date=e_fmt,
                            adjust="qfq"
                        )
                    else:
                        # A-share Stock
                        return ak.stock_zh_a_hist(
                            symbol=clean_ticker, period="daily",
                            start_date=s_fmt, end_date=e_fmt,
                            adjust="qfq"
                        )

                try:
                    df_remote = fetch_data()
                except (RequestException, Exception) as e:
                    if "Proxy" in str(e) or "proxy" in str(e):
                        logger.warning(f"⚠️ Proxy error detected: {e}. Retrying with proxy disabled...")
                        with temporary_no_proxy():
                            df_remote = fetch_data()
                    else:
                        raise e

                if df_remote is not None and not df_remote.empty:
                    df_remote = df_remote.rename(columns={
                        '日期': 'date', '开盘': 'open', '收盘': 'close',
                        '最高': 'high', '最低': 'low', '成交量': 'volume',
                        '涨跌幅': 'change_pct'
                    })
                    # 确保日期格式正确
                    df_remote['date'] = pd.to_datetime(df_remote['date']).dt.strftime('%Y-%m-%d')

                    # 只有在获取到有意义的数据时才保存
                    self.db.save_stock_prices(clean_ticker, df_remote) # 保存时使用清洗后的 clean_ticker

                    # 重新查询数据库返回结果，保证一致性
                    return self.db.get_stock_prices(clean_ticker, start_date, end_date)
                else:
                    logger.warning(f"⚠️ Akshare returned empty data for {clean_ticker}")

            except KeyError as e:
                # Akshare 有时在某些股票无数据时会抛出 KeyError
                logger.warning(f"⚠️ Akshare data missing for {clean_ticker}: {e}")
            except (RequestException, ConnectionError) as e:
                logger.error(f"❌ Network error during Akshare sync for {clean_ticker}: {e}")
            except sqlite3.Error as e:
                logger.error(f"❌ Database error during Akshare sync for {clean_ticker}: {e}")
            except Exception as e:
                logger.error(f"❌ Unexpected error during Akshare sync for {clean_ticker}: {e}")

        return df_db


def get_stock_analysis(ticker: str, db: DatabaseManager) -> str:
    """
    生成指定股票的分析摘要报告。

    Args:
        ticker: 股票代码
        db: 数据库管理器实例

    Returns:
        Markdown 格式的分析报告，包含价格走势和关键指标。
    """
    tools = StockTools(db)
    df = tools.get_stock_price(ticker)

    if df.empty:
        return f"❌ 未能获取 {ticker} 的股价数据。"

    latest = df.iloc[-1]
    change = ((latest['close'] - df.iloc[0]['close']) / df.iloc[0]['close']) * 100

    report = [
        f"## 📊 {ticker} 分析报告",
        f"- **查询时段**: {df.iloc[0]['date']} -> {latest['date']}",
        f"- **当前价**: ¥{latest['close']:.2f}",
        f"- **时段涨跌**: {change:+.2f}%",
        f"- **最高/最低**: ¥{df['high'].max():.2f} / ¥{df['low'].min():.2f}",
        "\n### 最近交易概览",
        "```",
        df.tail(5)[['date', 'close', 'change_pct', 'volume']].to_string(index=False),
        "```"
    ]
    return "\n".join(report)
