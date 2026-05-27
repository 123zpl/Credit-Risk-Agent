"""已通过 generate_sql 校验的 SQL 短期缓存，execute_sql 执行前必须命中。"""

from __future__ import annotations

import hashlib
import time

_TTL_SECONDS = 600  # 10 分钟内有效
_cache: dict[str, float] = {}


def _key(sql: str) -> str:
    normalized = sql.strip().rstrip(";")
    return hashlib.sha256(normalized.encode()).hexdigest()


def mark_sql_validated(sql: str) -> None:
    _cache[_key(sql)] = time.time() + _TTL_SECONDS
    _purge_expired()


def is_sql_validated(sql: str) -> bool:
    _purge_expired()
    expiry = _cache.get(_key(sql))
    return expiry is not None and expiry > time.time()


def clear_validation_cache() -> None:
    _cache.clear()


def _purge_expired() -> None:
    now = time.time()
    expired = [k for k, exp in _cache.items() if exp <= now]
    for k in expired:
        del _cache[k]
