from __future__ import annotations

from pathlib import Path
from datetime import datetime


def ensure_dirs() -> None:
    Path('data/cache').mkdir(parents=True, exist_ok=True)
    Path('output').mkdir(parents=True, exist_ok=True)


def today_str() -> str:
    return datetime.now().strftime('%Y%m%d')


def normalize_a_share_code(code: str) -> str:
    code = str(code).strip().upper().replace(' ', '')
    if code.endswith(('.SS', '.SZ', '.HK')):
        return code
    code = code.replace('.SH', '').replace('.SZ', '')
    
    # 5-digit is likely HK
    if len(code) == 5 and code.isdigit():
        return f'{code}.HK'
    
    # 6-digit is A-share
    if len(code) == 6 and code.isdigit():
        if code.startswith(('6', '9')):
            return f'{code}.SS'
        return f'{code}.SZ'
    
    # Otherwise assume US ticker or already normalized
    return code


def display_code(yahoo_code: str) -> str:
    return yahoo_code.replace('.SS', '').replace('.SZ', '').replace('.HK', '')
