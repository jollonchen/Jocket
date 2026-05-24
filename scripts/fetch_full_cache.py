import sys
import os
sys.path.append(os.getcwd())
import requests
import pandas as pd
from src.stock_lookup import _directory_cache_path

def fetch_all_a_shares():
    url = "https://72.push2.eastmoney.com/api/qt/clist/get"
    all_data = []
    for page in range(1, 150): # up to 150 pages
        params = {
            "pn": page,
            "pz": 100,
            "po": 1,
            "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2,
            "invt": 2,
            "wbp2u": "|0|0|0|web",
            "fid": "f3",
            "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
            "fields": "f12,f14",
        }
        r = requests.get(url, params=params, timeout=5)
        data = r.json().get("data")
        if not data:
            break
        diff = data.get("diff", [])
        if not diff:
            break
        all_data.extend(diff)
        
    df = pd.DataFrame(all_data)
    df = df.rename(columns={"f12": "code", "f14": "name"})
    df["source"] = "eastmoney_full"
    
    path = _directory_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"Saved {len(df)} stocks to {path}")

if __name__ == "__main__":
    fetch_all_a_shares()
