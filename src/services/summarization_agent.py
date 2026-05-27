"""
摘要压缩子 Agent（Summarization Sub-Agent）

职责：接收需要压缩的历史消息列表，调用 LLM 生成摘要字符串。
     支持滚动摘要：将上一次摘要内容作为上下文传入，生成涵盖全量历史的新摘要。

用法：
    from src.services.summarization_agent import SummarizationAgent
    agent = SummarizationAgent()
    summary = agent.summarize(messages_to_compress, previous_summary="...")
"""
from __future__ import annotations

import logging
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """你是一个对话历史摘要助手。
请将用户与 AI 助手的对话历史压缩为简洁、信息密度高的摘要。
摘要应保留：
- 用户的核心分析意图和关键问题
- AI 助手得出的重要结论和数据
- 对话中形成的业务判断和上下文背景

摘要长度控制在 300-600 字，使用中文。不需要加标题，直接输出摘要内容。"""


class SummarizationAgent:
    """
    LLM 摘要子 Agent。

    职责单一：给定消息列表 → 返回摘要字符串。
    失败时向调用方抛出异常，由调用方决定是否静默处理。
    """

    def __init__(self):
        from src.config import settings
        self._llm = ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            temperature=0.3,
            max_tokens=800,
        )

    def summarize(
        self,
        messages_to_compress: list[dict],
        previous_summary: str | None = None,
    ) -> str:
        """
        生成对话历史摘要。

        Args:
            messages_to_compress: 需要被压缩的消息列表（JSONL dict 格式，有 role/content 字段）
            previous_summary: 上一次摘要内容（滚动摘要场景）；None 表示首次压缩

        Returns:
            摘要字符串。messages_to_compress 为空时直接返回 ""。

        Raises:
            Exception: LLM 调用失败时向上抛出，由调用方决定是否静默。
        """
        if not messages_to_compress:
            return ""

        prompt_messages: list = [SystemMessage(content=_SYSTEM_PROMPT)]

        if previous_summary:
            prompt_messages.append(
                SystemMessage(content=f"【以下是截至上次压缩的历史摘要】\n{previous_summary}")
            )

        history_text = self._format_messages(messages_to_compress)
        prompt_messages.append(
            HumanMessage(content=f"【需要压缩的新增对话记录】\n{history_text}\n\n请生成摘要：")
        )

        response = self._llm.invoke(prompt_messages)
        return response.content.strip()

    @staticmethod
    def _format_messages(messages: list[dict]) -> str:
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            role_label = "用户" if role == "user" else "助手"
            lines.append(f"{role_label}：{content}")
        return "\n".join(lines)
