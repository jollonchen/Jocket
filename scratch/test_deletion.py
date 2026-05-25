import sys
import os
import shutil
from pathlib import Path

# Set up test path: ~/.tradingagents/logs/999999/TradingAgentsStrategy_logs/full_states_log_2026-05-23.json
test_home_logs = Path.home() / ".tradingagents" / "logs"
test_ticker_dir = test_home_logs / "999999"
test_strategy_logs_dir = test_ticker_dir / "TradingAgentsStrategy_logs"
test_file_path = test_strategy_logs_dir / "full_states_log_2026-05-23.json"

# Ensure clean state, then create test files
if test_ticker_dir.exists():
    shutil.rmtree(test_ticker_dir)

test_strategy_logs_dir.mkdir(parents=True, exist_ok=True)
with open(test_file_path, "w", encoding="utf-8") as f:
    f.write('{"company_of_interest": "999999", "trade_date": "2026-05-23"}')

print("Created test file at:", test_file_path)
print("File exists:", test_file_path.exists())
print("Parent dir exists:", test_strategy_logs_dir.exists())

# Perform our deletion and directory cleanup logic
try:
    p = Path(test_file_path)
    if p.exists():
        p.unlink()
        print("Success: File unlinked.")
        
        # Clean up empty parent directories up to logs dir
        parent_dir = p.parent
        if parent_dir.exists() and not os.listdir(parent_dir):
            parent_dir.rmdir()
            print("Success: Strategy logs directory rmdir-ed.")
            ticker_dir = parent_dir.parent
            if ticker_dir.exists() and not os.listdir(ticker_dir):
                ticker_dir.rmdir()
                print("Success: Ticker 999999 directory rmdir-ed.")
    else:
        print("Error: Test file does not exist when unlinking.")
except Exception as e:
    print("Exception during deletion:", e)

# Final verification
print("-" * 60)
print("Ticker dir still exists:", test_ticker_dir.exists())
print("Strategy logs dir still exists:", test_strategy_logs_dir.exists())
print("File still exists:", test_file_path.exists())
