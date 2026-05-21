import sys
import pandas as pd
from src.stock_lookup import build_stock_directory, resolve_stock_query
directory = build_stock_directory()
print(resolve_stock_query("工业富联短期走势怎么样", directory))
