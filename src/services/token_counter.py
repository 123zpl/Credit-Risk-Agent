"""
Token 计数工具

使用 tiktoken 本地计算 messages 列表的近似 token 数。
tiktoken 不可用时自动降级为字符数 ÷ 4 估算（误差 < 20%，足够触发压缩决策）。

用法：
    from src.services.token_counter import count_tokens
    total = count_tokens(messages)   # messages: list[dict]，每个 dict 有 "content" 字段
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    import tiktoken
    _ENCODING = tiktoken.get_encoding("cl100k_base")
    _USE_TIKTOKEN = True
except Exception:
    _ENCODING = None
    _USE_TIKTOKEN = False
    logger.warning("[TokenCounter] tiktoken unavailable, using char÷4 fallback")


def count_tokens(messages: list[dict]) -> int:
    """
    计算 messages 列表的总 token 数。

    - 有 tiktoken：用 cl100k_base 编码计算每条消息的 content
    - 无 tiktoken：sum(len(content)) // 4 估算

    Args:
        messages: list of dicts，每个 dict 应包含 "content" 字段（str）。
                  缺少 content 或 content 为空的行计 0。

    Returns:
        int: 估算的总 token 数
    """
    if not messages:
        return 0

    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if not content:
            continue
        if _USE_TIKTOKEN and _ENCODING is not None:
            total += len(_ENCODING.encode(str(content)))
        else:
            total += len(str(content)) // 4
    return total
