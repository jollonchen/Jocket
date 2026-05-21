import sys
from src.config import load_config
from src.ai_market_assistant import AIMarketAssistant
config = load_config()
assistant = AIMarketAssistant(config)
res = assistant.ask("工业富联短期走势怎么样")
print(res.get("answer"))
