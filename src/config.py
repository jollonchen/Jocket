from __future__ import annotations

from pathlib import Path
import yaml


def load_config(path: str = 'config.yaml') -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    with p.open('r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}
