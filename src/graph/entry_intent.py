"""
入口双重路由 — 规则意图分类（零 LLM）。

策略：
  - 含申请人 ID 且带审批/授信意图 → underwriting（由 entry_router 处理）
  - 命中 _MULTI_STEP_RE（为什么/分析/策略等）→ supervisor 规划
  - 命中 _DATA_QUERY_RE（逾期率/借呗等）→ data_query 直路由（无论有无历史）
  - 问候 / 空查询 / 模糊问题 → supervisor 兜底
  - 多轮对话的指代消解通过 data_query_node 注入历史用户 query 解决（不在此处理）
"""

from __future__ import annotations

import re
from typing import Literal

EntryRoute = Literal["underwriting", "supervisor", "data_query"]

_APPLICANT_ID_RE = re.compile(r"\bA[0-9A-Za-z]{6,}\b")

_UNDERWRITING_INTENT_RE = re.compile(
    r"(审批|授信|贷前|准入|申请人|评估.*风险|是否通过)",
    re.IGNORECASE,
)

_GREETING_RE = re.compile(
    r"^(你好|您好|hi|hello|hey|在吗|早上好|晚上好|你是谁|你能做什么|介绍一下)[\s\?？!！。.，,~～]*$",
    re.IGNORECASE,
)

# 需要 Supervisor 规划的多步 / 复杂意图
_MULTI_STEP_RE = re.compile(
    r"原因|为什么|为何|归因|分析|策略|建议|如何降低|怎么办|合规|监管|违规|审查",
    re.IGNORECASE,
)

# 明确的纯数据查询信号
_DATA_QUERY_RE = re.compile(
    r"逾期率|贷款数|数量|多少|是多少|有多少|查询|统计|分布|比例|趋势|对比|"
    r"评级|借呗|花呗|网商贷|放款|还款|利率|金额|用户数|客群|概况|各.{0,8}级",
    re.IGNORECASE,
)


def classify_entry_route(query: str, *, has_history: bool = False) -> EntryRoute:
    """
    规则分类入口路由目标（不含 applicant_id，由 entry_router 优先处理）。

    路由结果只取决于 query 文本内容，与历史对话无关：
    - 命中 _MULTI_STEP_RE（为什么/分析/策略等）→ supervisor
    - 命中 _DATA_QUERY_RE（逾期率/借呗/查询等）→ data_query
    - 问候 / 空 / 模糊 → supervisor 兜底

    has_history 参数保留以兼容旧调用，但不再影响路由决策。
    多轮对话的指代消解由 data_query_node 通过注入历史 query 解决。

    Returns:
        data_query  — 单步纯查数，直进 data_query Agent
        supervisor  — 问候、复杂任务、模糊意图
    """
    _ = has_history  # 保留参数兼容性，不再使用

    q = (query or "").strip()
    if not q:
        return "supervisor"
    if _GREETING_RE.match(q):
        return "supervisor"
    if _MULTI_STEP_RE.search(q):
        return "supervisor"
    if _DATA_QUERY_RE.search(q):
        return "data_query"
    return "supervisor"


def is_applicant_underwriting_query(query: str) -> bool:
    q = (query or "").strip()
    if not _APPLICANT_ID_RE.search(q):
        return False
    return bool(_UNDERWRITING_INTENT_RE.search(q))
