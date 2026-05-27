"""Redis 会话上下文管理：支持多轮对话上下文存储和检索"""

import json
import logging
from typing import Any

from src.database import redis_client

logger = logging.getLogger(__name__)

SESSION_PREFIX = "session:"
SESSION_TTL = 1800  # 30 minutes


def _key(session_id: str) -> str:
    return f"{SESSION_PREFIX}{session_id}"


def save_session_context(session_id: str, data: dict[str, Any]):
    """保存会话上下文到 Redis Hash（TTL 30 分钟，每次写入刷新）"""
    key = _key(session_id)
    try:
        serialized = {}
        for k, v in data.items():
            serialized[k] = json.dumps(v, ensure_ascii=False, default=str) if not isinstance(v, str) else v
        redis_client.hset(key, mapping=serialized)
        redis_client.expire(key, SESSION_TTL)
    except Exception as e:
        logger.warning(f"Failed to save session context: {e}")


def load_session_context(session_id: str) -> dict[str, Any]:
    """从 Redis 加载会话上下文"""
    key = _key(session_id)
    try:
        raw = redis_client.hgetall(key)
        if not raw:
            return {}
        result = {}
        for k, v in raw.items():
            try:
                result[k] = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                result[k] = v
        redis_client.expire(key, SESSION_TTL)
        return result
    except Exception as e:
        logger.warning(f"Failed to load session context: {e}")
        return {}


def append_history(session_id: str, query: str, intent: str, report_summary: str):
    """追加一轮对话到会话历史"""
    key = _key(session_id)
    try:
        history_raw = redis_client.hget(key, "history")
        history = json.loads(history_raw) if history_raw else []
        history.append({
            "query": query,
            "intent": intent,
            "summary": report_summary[:500],
        })
        if len(history) > 10:
            history = history[-10:]
        redis_client.hset(key, "history", json.dumps(history, ensure_ascii=False))
        redis_client.expire(key, SESSION_TTL)
    except Exception as e:
        logger.warning(f"Failed to append history: {e}")


def get_history(session_id: str) -> list[dict]:
    """获取会话历史"""
    key = _key(session_id)
    try:
        history_raw = redis_client.hget(key, "history")
        return json.loads(history_raw) if history_raw else []
    except Exception as e:
        logger.warning(f"Failed to get history: {e}")
        return []


def delete_session(session_id: str):
    """删除会话"""
    try:
        redis_client.delete(_key(session_id))
    except Exception as e:
        logger.warning(f"Failed to delete session: {e}")
