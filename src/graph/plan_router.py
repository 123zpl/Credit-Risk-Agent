"""
plan_router — 纯 Python 路由函数，驱动 Plan-then-Execute 流转。

设计原则：
  - 零 LLM 调用，零延迟，只读 state.execution_plan 和 state.plan_index
  - 所有工具 Agent 节点完成后统一调用此函数决定下一站
  - 不含任何业务逻辑，只做路由决策

入口双重路由策略：
  - 含申请人 ID 且带审批意图 → underwriting（贷前审批，独立子图）
  - 命中纯数据查询关键词 → data_query（直路由，跳过 Supervisor plan，无论有无历史）
  - 命中多步分析关键词 / 问候 / 模糊 → supervisor（主 Agent）
  - 多轮对话指代消解由 data_query_node 注入历史 user query 解决
"""
from __future__ import annotations

from src.graph.entry_intent import classify_entry_route, is_applicant_underwriting_query
from src.graph.plan_constants import WORKER_STEPS
# 工具 Agent 节点完成后的路由映射（plan_router 使用，不含 clarify）
# plan 耗尽时路由到 supervisor_respond（主 Agent 统一生成最终回复）
PLAN_ROUTE_MAP: dict[str, str] = {
    "data_query":         "data_query",
    "risk_analysis":      "risk_analysis",
    "compliance":         "compliance",
    "strategy":           "strategy",
    "supervisor_respond": "supervisor_respond",
    "direct_worker_response": "direct_worker_response",
}


def data_query_exit_router(state) -> str:
    """
    data_query Worker 完成后的出口路由：
    - entry_route_mode=direct_data_query → 直出 Worker 结果，不经 supervisor_respond
    - 其余（Supervisor plan 中的 data_query 步骤）→ 按 plan_router 继续
    """
    if getattr(state, "entry_route_mode", "") == "direct_data_query":
        return "direct_worker_response"
    return plan_router(state)

# 申请人 ID 格式（A + 6位以上字母数字）— 保留 re-export 供测试兼容
import re
_APPLICANT_ID_RE = re.compile(r"\bA[0-9A-Za-z]{6,}\b")

def plan_router(state) -> str:
    """
    读取 state.execution_plan[state.plan_index]，返回下一个节点名称。
    plan 执行完毕（或空 plan）时路由到 supervisor_respond，由主 Agent 统一回复。
    非法 step 跳过至 supervisor_respond，避免 conditional_edges KeyError。
    """
    idx = state.plan_index
    plan = state.execution_plan
    if not plan or idx >= len(plan):
        return "supervisor_respond"
    step = plan[idx]
    if step not in WORKER_STEPS:
        return "supervisor_respond"
    return step


def supervisor_entry_router(state) -> str:
    """
    Supervisor 节点完成后的路由：
    - intent=direct_reply → 直接结束（LLM 已直接回复，final_report 已写入）
    - intent=clarify      → 直接结束（澄清问题已写入 final_report）
    - 其余                → 按 plan_router 路由到第一个 Worker
    """
    intent = getattr(state, "intent", None)
    if intent in ("direct_reply", "clarify"):
        return "direct_reply"   # 统一映射到 END
    return plan_router(state)


def entry_router(state) -> str:
    """
    系统入口双重路由（纯 Python，零 LLM）：
    - 含申请人 ID + 审批意图 → underwriting
    - 纯数据查询关键词 → data_query（直路由，不经 Supervisor plan；多轮指代由 node 内注入历史解决）
    - 多步分析关键词 / 问候 / 模糊 → supervisor
    """
    query = (getattr(state, "user_query", "") or "").strip()
    if is_applicant_underwriting_query(query):
        return "underwriting"
    has_history = bool(getattr(state, "messages", None))
    return classify_entry_route(query, has_history=has_history)
