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
    if code.endswith('.SS') or code.endswith('.SZ'):
        return code
    code = code.replace('.SH', '').replace('.SZ', '')
    if len(code) != 6 or not code.isdigit():
        return code
    if code.startswith(('6', '9')):
        return f'{code}.SS'
    return f'{code}.SZ'


def display_code(yahoo_code: str) -> str:
    return yahoo_code.replace('.SS', '').replace('.SZ', '')
