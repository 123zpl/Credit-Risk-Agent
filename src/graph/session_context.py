"""会话上下文构建：将历史对话与结构化状态注入 user_query。"""


def format_history_block(history: list[dict]) -> str:
    if not history:
        return ""
    recent = history[-3:]
    lines = [f"- 用户问: {h['query']} (意图: {h['intent']})" for h in recent]
    return "对话历史：\n" + "\n".join(lines)


def format_session_block(session_ctx: dict) -> str:
    if not session_ctx:
        return ""
    parts: list[str] = []
    if session_ctx.get("last_intent"):
        parts.append(f"上轮意图: {session_ctx['last_intent']}")
    if session_ctx.get("last_data_summary"):
        parts.append(f"上轮数据摘要: {session_ctx['last_data_summary']}")
    if session_ctx.get("last_query"):
        parts.append(f"上轮问题: {session_ctx['last_query']}")
    return "\n".join(parts)


def build_contextual_query(query: str, history: list[dict], session_ctx: dict) -> str:
    """拼接多轮上下文；无历史且无会话状态时返回原始 query。"""
    blocks: list[str] = []
    history_block = format_history_block(history)
    if history_block:
        blocks.append(history_block)
    session_block = format_session_block(session_ctx)
    if session_block:
        blocks.append(session_block)
    if not blocks:
        return query
    blocks.append(f"当前问题：\n{query}")
    return "\n\n".join(blocks)
