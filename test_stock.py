import sys
from src.config import load_config
from src.ai_market_assistant import AIMarketAssistant
config = load_config()
assistant = AIMarketAssistant(config)
res = assistant._fetch_stock_skill_context("工业富联短期走势怎么样")
print("RESULT:", res)
