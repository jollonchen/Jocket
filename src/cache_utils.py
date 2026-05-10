from __future__ import annotations

import json
import pickle
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .utils import ensure_dirs


@dataclass
class DataSourceError:
    source: str
    interface: str
    error_type: str
    message: str
    occurred_at: str
    fallback_used: str = ""

    @classmethod
    def from_exception(cls, source: str, interface: str, exc: Exception, fallback_used: str = "") -> "DataSourceError":
        return cls(
            source=source,
            interface=interface,
            error_type=exc.__class__.__name__,
            message=str(exc),
            occurred_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            fallback_used=fallback_used,
        )

    def to_dict(self) -> dict:
        return asdict(self)


class FileCache:
    def __init__(self, base_dir: str | Path = "data/cache"):
        ensure_dirs()
        self.base_dir = Path(base_dir)
        for subdir in ["price", "fundamentals", "profile", "industry", "moneyflow", "news", "logs"]:
            (self.base_dir / subdir).mkdir(parents=True, exist_ok=True)

    def path(self, namespace: str, key: str, ext: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in key)
        return self.base_dir / namespace / f"{safe}.{ext}"

    @staticmethod
    def fresh(path: Path, ttl_seconds: int) -> bool:
        return path.exists() and (time.time() - path.stat().st_mtime) <= ttl_seconds

    def get_pickle(self, namespace: str, key: str, ttl_seconds: int):
        path = self.path(namespace, key, "pkl")
        if not self.fresh(path, ttl_seconds):
            return None
        try:
            with path.open("rb") as f:
                value = pickle.load(f)
            if isinstance(value, pd.DataFrame):
                value.attrs["from_cache"] = True
            elif isinstance(value, dict):
                value["_from_cache"] = True
            return value
        except Exception:
            return None

    def set_pickle(self, namespace: str, key: str, value: Any) -> None:
        path = self.path(namespace, key, "pkl")
        with path.open("wb") as f:
            pickle.dump(value, f)

    def log_error(self, error: DataSourceError) -> None:
        path = self.base_dir / "logs" / f"errors_{datetime.now().strftime('%Y%m%d')}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(error.to_dict(), ensure_ascii=False) + "\n")


class RequestLimiter:
    _last_request: dict[str, float] = {}

    def __init__(self, min_interval: float = 1.0):
        self.min_interval = min_interval

    def wait(self, source: str) -> None:
        now = time.time()
        last = self._last_request.get(source, 0)
        delay = self.min_interval - (now - last)
        if delay > 0:
            time.sleep(delay)
        self._last_request[source] = time.time()


def safe_fetch(
    source: str,
    interface: str,
    func: Callable[[], Any],
    *,
    retries: int = 2,
    delays: tuple[float, ...] = (1.0, 3.0, 8.0),
    min_interval: float = 1.0,
    cache: FileCache | None = None,
) -> tuple[Any, list[dict]]:
    limiter = RequestLimiter(min_interval=min_interval)
    errors: list[dict] = []
    attempts = max(1, retries + 1)
    for attempt in range(attempts):
        try:
            limiter.wait(source)
            value = func()
            if value is None:
                raise ValueError("接口返回空内容")
            if isinstance(value, pd.DataFrame) and value.empty:
                raise ValueError("接口返回空 DataFrame")
            return value, errors
        except Exception as exc:
            fallback = "retry" if attempt < attempts - 1 else "degraded"
            err = DataSourceError.from_exception(source, interface, exc, fallback)
            errors.append(err.to_dict())
            if cache:
                cache.log_error(err)
            if attempt < attempts - 1:
                time.sleep(delays[min(attempt, len(delays) - 1)])
    return None, errors


def compact_error_message(error: dict | str) -> str:
    if isinstance(error, str):
        text = error
    else:
        text = f"{error.get('source', '')} {error.get('interface', '')} 暂不可用"
    return text.strip() or "数据源暂不可用"
