"""Router 意图解析辅助函数（纯函数，便于单元测试）。"""

import re

from src.graph.legacy_routing import INTENT_LABELS

_GREETING_RE = re.compile(
    r"^(你好|您好|hi|hello|hey|在吗|早上好|晚上好|你是谁|你能做什么)[\s\?？!！。.，,~～]*$",
    re.IGNORECASE,
)


def parse_intent_from_router_output(raw: str) -> str:
    """从 Router LLM 输出解析意图标签；不对用户自然语言做子串误判。"""
    text = (raw or "").strip().lower()
    if not text:
        return "data_query"
    if _GREETING_RE.match(text):
        return "chitchat"

    for line in text.splitlines():
        candidate = line.strip().strip("`\"'：: ")
        if candidate.startswith("意图"):
            candidate = candidate.split(":", 1)[-1].split("：", 1)[-1].strip()
        if candidate in INTENT_LABELS:
            return candidate

    for candidate in INTENT_LABELS:
        if re.search(rf"\b{re.escape(candidate)}\b", text):
            return candidate

    return "data_query"
