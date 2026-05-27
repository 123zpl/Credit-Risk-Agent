"""
Multi-Agent 信贷风控分析工作流（LangGraph 编排）

流程:
  用户输入 -> Router(意图识别) -> 分发到对应 Agent 子图
    - chitchat -> chat 节点（寒暄，不走全链路）
    - 数据查询类 -> DataQueryAgent -> 直接返回
    - 风险分析类 -> DataQueryAgent -> RiskAnalysisAgent -> StrategyAgent -> ComplianceAgent -> 汇总
    - 合规检查类 -> DataQueryAgent -> ComplianceAgent -> 汇总
    - 策略建议类 -> DataQueryAgent -> RiskAnalysisAgent -> StrategyAgent -> ComplianceAgent -> 汇总
"""

import json
import re
import uuid
import time
import operator
from typing import Annotated, Literal

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel, Field

from src.config import settings
from src.agents.data_query_agent import create_data_query_agent
from src.agents.risk_analysis_agent import create_risk_analysis_agent
from src.agents.compliance_agent import create_compliance_agent
from src.agents.strategy_agent import create_strategy_agent
from src.services.log_service import persist_execution_log, persist_report, persist_strategy
from src.services.memory_store import to_langchain_messages
from src.underwriting.decision_service import _extract_json_text, build_rule_decision
from src.underwriting.policy_retrieval import retrieve_policies_from_applicant_info
from src.underwriting.underwriting_policy import rule_based_decision as rule_based_underwriting_decision
from src.agents.underwriting_agent import create_underwriting_agent
from src.tools.underwriting_tools import (
    calculate_risk_score,
    check_underwriting_compliance,
    get_applicant_info,
    match_similar_users,
)
from src.graph.supervisor import supervisor_node, supervisor_respond_node
from src.graph.synthesis_context import cap_worker_output, smart_truncate_text
from src.graph.plan_router import (
    PLAN_ROUTE_MAP,
    plan_router,
    supervisor_entry_router,
    entry_router,
    data_query_exit_router,
)

from src.graph.tool_trace import (
    get_tool_traces,
    merge_agent_config,
    reset_tool_traces,
    tool_trace_log_entries,
)


_AGENT_RECURSION_LIMITS: dict[str, int] = {
    # data_query 两阶段：schema + generate_sql(含重试) + execute_sql + 最终回复
    # 每次 tool call ≈ 2 步（model→tool→model），6 次工具调用需 ~18 步，留余量设 25
    "data_query_agent": 25,
}
_DEFAULT_RECURSION_LIMIT = 15


def _agent_invoke_config(session_id: str, agent_name: str, step: int) -> dict:
    """Agent 调用 config；节点级 LangSmith 由 LANGSMITH_NODE_TRACING 控制。"""
    cfg: dict = {"recursion_limit": _AGENT_RECURSION_LIMITS.get(agent_name, _DEFAULT_RECURSION_LIMIT)}
    if settings.langsmith_node_tracing:
        cfg.update({
            "run_name": agent_name,
            "metadata": {"session_id": session_id, "step": step},
            "tags": ["credit-risk", agent_name],
        })
    return merge_agent_config(cfg)


def _flush_tool_logs(session_id: str, agent_name: str, step: int) -> list[dict]:
    logs: list[dict] = []
    for entry in tool_trace_log_entries(agent_name, step, get_tool_traces()):
        logs.extend(_persist_and_log(session_id, entry))
    return logs


# ============================================
# 状态定义
# ============================================

class WorkflowState(BaseModel):
    """工作流全局状态"""
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_query: str = ""
    intent: str = ""

    # 完整的多轮对话 messages（由 memory_store 注入，仅 supervisor_node 读取）
    messages: list[dict] = Field(default_factory=list)

    # ── Supervisor Plan-then-Execute 字段 ──────────────────────────────────
    # Supervisor 规划的执行步骤列表，如 ["data_query", "risk_analysis"]
    execution_plan: list[str] = Field(default_factory=list)
    # 各步骤的精准 task 检查单，如 {"data_query": "查询近6个月逾期率趋势"}
    task_instructions: dict[str, str] = Field(default_factory=dict)
    # 当前执行到第几步（plan_router 读此值决定下一站）
    plan_index: int = 0

    # 入口路由模式：direct_data_query = 规则直路由查数，跳过 supervisor_respond
    entry_route_mode: str = ""

    data_result: str = ""
    risk_result: str = ""
    compliance_result: str = ""
    strategy_result: str = ""
    final_report: str = ""

    execution_log: Annotated[list[dict], operator.add] = Field(default_factory=list)
    current_step: int = 0


class UnderwritingState(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    applicant_id: str = ""
    applicant_info: str = ""
    similar_users_result: str = ""
    policy_rag_result: str = ""
    risk_score_result: str = ""
    decision_result: str = ""
    compliance_result: str = ""
    approval_report: str = ""
    final_decision: dict = Field(default_factory=dict)
    execution_log: Annotated[list[dict], operator.add] = Field(default_factory=list)
    current_step: int = 0


# ============================================
# 节点函数
# ============================================

def _persist_and_log(session_id: str, log_entry: dict) -> list[dict]:
    persist_execution_log(session_id, log_entry)
    return [log_entry]


def _enrich_with_history_queries(
    task: str,
    messages: list[dict],
    *,
    max_turns: int = 3,
) -> str:
    """注入最近 max_turns 条用户 query 到 task 前面，用于多轮对话指代消解。

    设计原则：
      - 只取 role=user 的消息（不取 assistant 回复，控制 token 成本）
      - 用明确的 [历史用户query] 和 [当前问题] 标记分隔
      - 历史为空时返回原 task，不报错
      - 跳过空 content 和缺失 role 的消息

    Args:
        task: 当前任务描述（来自 task_instructions 或 user_query）
        messages: state.messages，每条形如 {"role": "user"|"assistant", "content": "..."}
        max_turns: 最多取最近多少条 user query（默认 3）

    Returns:
        若有历史：拼接好的 task 字符串；若无历史：原 task
    """
    if not messages:
        return task

    user_queries: list[str] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "user":
            continue
        content = (msg.get("content") or "").strip()
        if content:
            user_queries.append(content)

    recent = user_queries[-max_turns:]
    if not recent:
        return task

    history_block = "\n".join(f"- {q}" for q in recent)
    return (
        f"[历史用户query]（仅供指代消解，不要重复回答历史问题）：\n"
        f"{history_block}\n\n"
        f"[当前问题]：\n{task}"
    )


def direct_data_query_prepare(state: WorkflowState) -> dict:
    """
    规则直路由 data_query 前的 state 初始化（跳过 Supervisor plan，零 LLM）。
    """
    return {
        "intent": "data_query",
        "entry_route_mode": "direct_data_query",
        "execution_plan": ["data_query"],
        "task_instructions": {"data_query": state.user_query},
        "plan_index": 0,
        "current_step": 1,
        "execution_log": [{
            "agent": "entry_router",
            "step": 0,
            "action": "rule_direct_data_query",
            "result": f"规则直路由: {state.user_query[:80]}",
            "latency_ms": 0,
        }],
    }


def direct_worker_response_node(state: WorkflowState) -> dict:
    """
    直路由 Worker 的最终回复节点 — 不调用 LLM，直接采用 Worker 输出。

    用于 entry_route_mode=direct_data_query：data_query 完成后直接写 final_report。
    """
    report = (state.data_result or "").strip() or "查询无结果"
    persist_report(
        session_id=state.session_id,
        query=state.user_query,
        intent=state.intent or "data_query",
        report=report,
        data_result=state.data_result,
        risk_result=state.risk_result,
        strategy_result=state.strategy_result,
        compliance_result=state.compliance_result,
    )
    log_entry = {
        "agent": "direct_worker_response",
        "step": state.current_step,
        "action": "passthrough_data_query",
        "result": "直路由：采用 data_query 结果作为最终回复",
        "latency_ms": 0,
    }
    return {
        "final_report": report,
        "execution_log": _persist_and_log(state.session_id, log_entry),
    }


def data_query_node(state: WorkflowState) -> dict:
    start = time.time()
    agent = create_data_query_agent()
    reset_tool_traces()

    base_task = state.task_instructions.get("data_query") or state.user_query
    # 多轮对话：注入最近 3 条用户 query 到 task 前面（指代消解）
    task = _enrich_with_history_queries(base_task, state.messages)
    result = agent.invoke(
        {"messages": [HumanMessage(content=task)]},
        _agent_invoke_config(state.session_id, "data_query_agent", state.current_step),
    )

    output = result["messages"][-1].content if result["messages"] else "查询无结果"
    elapsed = int((time.time() - start) * 1000)
    tool_logs = _flush_tool_logs(state.session_id, "data_query_agent", state.current_step)

    log_entry = {
        "agent": "data_query_agent",
        "step": state.current_step,
        "action": "text_to_sql_query",
        "result": output[:500],
        "latency_ms": elapsed,
    }
    # Worker 只写结构化中间结果，final_report 由 supervisor_respond_node 统一生成
    return {
        "data_result": cap_worker_output(output),
        "plan_index": state.plan_index + 1,
        "execution_log": tool_logs + _persist_and_log(state.session_id, log_entry),
        "current_step": state.current_step + 1,
    }


def risk_analysis_node(state: WorkflowState) -> dict:
    start = time.time()
    agent = create_risk_analysis_agent()
    reset_tool_traces()

    # 无状态：精准检查单 + 本轮数据结果（不传历史 messages）
    base_task = state.task_instructions.get("risk_analysis") or state.user_query
    task = base_task
    if state.data_result:
        task += f"\n\n本轮数据查询结果：\n{smart_truncate_text(state.data_result, 2000)}"

    result = agent.invoke(
        {"messages": [HumanMessage(content=task)]},
        _agent_invoke_config(state.session_id, "risk_analysis_agent", state.current_step),
    )

    output = result["messages"][-1].content if result["messages"] else "分析无结果"
    elapsed = int((time.time() - start) * 1000)
    tool_logs = _flush_tool_logs(state.session_id, "risk_analysis_agent", state.current_step)

    log_entry = {
        "agent": "risk_analysis_agent",
        "step": state.current_step,
        "action": "risk_attribution",
        "result": output[:500],
        "latency_ms": elapsed,
    }
    # Worker 只写结构化中间结果，final_report 由 supervisor_respond_node 统一生成
    return {
        "risk_result": cap_worker_output(output),
        "plan_index": state.plan_index + 1,
        "execution_log": tool_logs + _persist_and_log(state.session_id, log_entry),
        "current_step": state.current_step + 1,
    }


def compliance_node(state: WorkflowState) -> dict:
    start = time.time()
    agent = create_compliance_agent()
    reset_tool_traces()

    # 无状态：精准检查单 + 本轮相关内容（不传历史 messages）
    base_task = state.task_instructions.get("compliance") or "请对以下内容进行合规审查"
    parts = [base_task]
    if state.strategy_result:
        parts.append(f"\n待审查策略：\n{smart_truncate_text(state.strategy_result, 2000)}")
    if state.data_result:
        parts.append(f"\n相关数据：\n{smart_truncate_text(state.data_result, 1000)}")
    if state.risk_result:
        parts.append(f"\n风险分析结论：\n{smart_truncate_text(state.risk_result, 1000)}")
    task = "\n".join(parts)

    result = agent.invoke(
        {"messages": [HumanMessage(content=task)]},
        _agent_invoke_config(state.session_id, "compliance_agent", state.current_step),
    )

    output = result["messages"][-1].content if result["messages"] else "合规检查无结果"
    elapsed = int((time.time() - start) * 1000)
    tool_logs = _flush_tool_logs(state.session_id, "compliance_agent", state.current_step)

    log_entry = {
        "agent": "compliance_agent",
        "step": state.current_step,
        "action": "compliance_check",
        "result": output[:500],
        "latency_ms": elapsed,
    }
    # Worker 只写结构化中间结果，final_report 由 supervisor_respond_node 统一生成
    return {
        "compliance_result": cap_worker_output(output),
        "plan_index": state.plan_index + 1,
        "execution_log": tool_logs + _persist_and_log(state.session_id, log_entry),
        "current_step": state.current_step + 1,
    }


def strategy_node(state: WorkflowState) -> dict:
    start = time.time()
    agent = create_strategy_agent()
    reset_tool_traces()

    # 无状态：精准检查单 + 本轮风险结论（不传历史 messages）
    base_task = state.task_instructions.get("strategy") or state.user_query
    parts = [base_task]
    if state.risk_result:
        parts.append(f"\n风险分析结论：\n{smart_truncate_text(state.risk_result, 2000)}")
    if state.data_result:
        parts.append(f"\n原始数据：\n{smart_truncate_text(state.data_result, 1000)}")
    task = "\n".join(parts)

    result = agent.invoke(
        {"messages": [HumanMessage(content=task)]},
        _agent_invoke_config(state.session_id, "strategy_agent", state.current_step),
    )

    output = result["messages"][-1].content if result["messages"] else "策略生成无结果"
    elapsed = int((time.time() - start) * 1000)
    tool_logs = _flush_tool_logs(state.session_id, "strategy_agent", state.current_step)

    persist_strategy(state.session_id, output)

    log_entry = {
        "agent": "strategy_agent",
        "step": state.current_step,
        "action": "strategy_generation",
        "result": output[:500],
        "latency_ms": elapsed,
    }
    return {
        "strategy_result": cap_worker_output(output),
        "plan_index": state.plan_index + 1,
        "execution_log": tool_logs + _persist_and_log(state.session_id, log_entry),
        "current_step": state.current_step + 1,
    }



def _json_obj(payload: str | dict | None) -> dict:
    if isinstance(payload, dict):
        return payload
    if not payload:
        return {}
    try:
        return json.loads(payload)
    except Exception:
        return {}


def _safe_tool_invoke(tool_fn, **kwargs) -> str:
    """Underwriting 并行分支工具调用容错：失败时返回结构化 error JSON。"""
    try:
        return tool_fn.invoke(kwargs)
    except Exception as e:
        tool_name = getattr(tool_fn, "name", getattr(tool_fn, "__name__", "unknown_tool"))
        return json.dumps({"error": str(e), "tool": tool_name}, ensure_ascii=False)


def fetch_applicant_node(state: UnderwritingState) -> dict:
    raw = _safe_tool_invoke(get_applicant_info, applicant_id=state.applicant_id)
    return {"applicant_info": raw, "current_step": state.current_step + 1}


def match_similar_node(state: UnderwritingState) -> dict:
    raw = _safe_tool_invoke(match_similar_users, applicant_id=state.applicant_id, top_k=100)
    # fan-out 分支不写 current_step，避免并行节点冲突
    return {"similar_users_result": raw}


def retrieve_policies_node(state: UnderwritingState) -> dict:
    start = time.time()
    try:
        raw = retrieve_policies_from_applicant_info(state.applicant_info)
    except Exception as e:
        raw = json.dumps({"error": str(e), "tool": "policy_retrieval"}, ensure_ascii=False)
    payload = _json_obj(raw)
    elapsed = int((time.time() - start) * 1000)
    log_entry = {
        "agent": "policy_retrieval",
        "step": state.current_step,
        "action": "rag_dual_collection_search",
        "result": f"检索到 {payload.get('命中条款数', 0)} 条相关政策/法规条款",
        "latency_ms": elapsed,
    }
    return {
        "policy_rag_result": raw,
        "execution_log": [log_entry],
    }


def risk_scoring_node(state: UnderwritingState) -> dict:
    raw = _safe_tool_invoke(calculate_risk_score, applicant_id=state.applicant_id)
    return {"risk_score_result": raw}


def _branch_had_tool_error(*payloads: str) -> bool:
    for raw in payloads:
        obj = _json_obj(raw)
        if obj.get("error"):
            return True
    return False


def underwriting_decision_node(state: UnderwritingState) -> dict:
    start = time.time()
    applicant = _json_obj(state.applicant_info).get("applicant", {})
    similar = _json_obj(state.similar_users_result)
    score = _json_obj(state.risk_score_result)
    branch_errors = _branch_had_tool_error(
        state.applicant_info,
        state.similar_users_result,
        state.risk_score_result,
        state.policy_rag_result or "",
    )
    rule = build_rule_decision(applicant, similar, score)

    context = f"""请基于以下信息给出审批决策并撰写审批报告。

## 申请人信息
{state.applicant_info}

## 历史同类用户
{state.similar_users_result}

## 风险评分
{state.risk_score_result}

## 相关政策法规（RAG检索结果）
{state.policy_rag_result or '{"命中条款数": 0, "检索结果": []}'}
"""

    approval_report = ""
    parsed: dict = {}
    try:
        agent = create_underwriting_agent()
        result = agent.invoke(
            {"messages": [{"role": "user", "content": context}]},
            _agent_invoke_config(state.session_id, "underwriting_agent", state.current_step),
        )
        messages = result.get("messages") if isinstance(result, dict) else None
        content = ""
        if messages:
            content = getattr(messages[-1], "content", "") or str(messages[-1])
        parsed = _extract_json_text(content)
        approval_report = str(parsed.get("approval_report") or "")
    except Exception:
        parsed = {}

    decision = {**rule, **parsed}
    decision["approval_report"] = approval_report or parsed.get("approval_report", "")
    if branch_errors or (not approval_report and not parsed.get("decision")):
        decision = rule
        decision["approval_report"] = (
            "## 审批结论\n"
            f"- 决策: {rule.get('decision')}\n\n"
            "## 政策依据\n"
            + (
                "- 部分并行分支（相似用户/评分/RAG）调用失败，已基于规则引擎兜底审批。"
                if branch_errors
                else "- 本次审批缺少政策库校验或 Agent 不可用，基于系统内置规则执行。"
            )
        )

    elapsed = int((time.time() - start) * 1000)
    return {
        "decision_result": json.dumps(decision, ensure_ascii=False),
        "approval_report": decision.get("approval_report", ""),
        "final_decision": decision,
        "execution_log": [{
            "agent": "underwriting_agent",
            "step": state.current_step,
            "action": "decision_and_report",
            "result": f"决策: {decision.get('decision')}, 报告: {len(decision.get('approval_report', ''))} chars",
            "latency_ms": elapsed,
        }],
        "current_step": state.current_step + 1,
    }


def compliance_check_node(state: UnderwritingState) -> dict:
    decision = state.final_decision or _json_obj(state.decision_result)
    raw = check_underwriting_compliance.invoke(
        {
            "applicant_id": state.applicant_id,
            "suggested_amount": float(decision.get("suggested_amount") or 0),
            "suggested_rate": float(decision.get("suggested_rate") or 0),
        }
    )
    compliance = _json_obj(raw)
    merged = dict(decision)
    merged["compliance_check"] = compliance
    return {
        "compliance_result": raw,
        "final_decision": merged,
        "current_step": state.current_step + 1,
    }


def extract_applicant_id_from_query(query: str) -> str:
    match = re.search(r"\bA[0-9A-Za-z]{6,}\b", query or "")
    return match.group(0) if match else ""


def build_underwriting_workflow() -> StateGraph:
    graph = StateGraph(UnderwritingState)
    graph.add_node("fetch_applicant", fetch_applicant_node)
    graph.add_node("match_similar", match_similar_node)
    graph.add_node("retrieve_policies", retrieve_policies_node)
    graph.add_node("risk_scoring", risk_scoring_node)
    graph.add_node("underwriting_decision", underwriting_decision_node)
    graph.add_node("compliance_check", compliance_check_node)

    graph.add_edge(START, "fetch_applicant")

    # fan-out：fetch_applicant 完成后，三个独立节点并行执行
    graph.add_edge("fetch_applicant", "match_similar")
    graph.add_edge("fetch_applicant", "retrieve_policies")
    graph.add_edge("fetch_applicant", "risk_scoring")

    # fan-in：三个节点全部完成后，LangGraph 自动汇聚再进入 underwriting_decision
    graph.add_edge("match_similar",     "underwriting_decision")
    graph.add_edge("retrieve_policies", "underwriting_decision")
    graph.add_edge("risk_scoring",      "underwriting_decision")

    graph.add_edge("underwriting_decision", "compliance_check")
    graph.add_edge("compliance_check", END)
    return graph.compile()


def underwriting_node(state: WorkflowState) -> dict:
    start = time.time()
    applicant_id = extract_applicant_id_from_query(state.user_query)
    if not applicant_id:
        msg = "未识别到申请人ID，请使用如 A123456 的申请人编号发起审批。"
        log_entry = {
            "agent": "underwriting",
            "step": state.current_step,
            "action": "underwriting_parse",
            "result": msg,
            "latency_ms": int((time.time() - start) * 1000),
        }
        return {
            "final_report": msg,
            "execution_log": _persist_and_log(state.session_id, log_entry),
            "current_step": state.current_step + 1,
        }

    workflow = build_underwriting_workflow()
    result = workflow.invoke(UnderwritingState(session_id=state.session_id, applicant_id=applicant_id).model_dump())
    decision = result.get("final_decision", {})
    elapsed = int((time.time() - start) * 1000)
    report = json.dumps({"applicant_id": applicant_id, **decision}, ensure_ascii=False, default=str)
    log_entry = {
        "agent": "underwriting",
        "step": state.current_step,
        "action": "underwriting_workflow",
        "result": "审批完成",
        "latency_ms": elapsed,
    }
    return {
        "final_report": report,
        "execution_log": _persist_and_log(state.session_id, log_entry),
        "current_step": state.current_step + 1,
    }


def build_workflow() -> StateGraph:
    """
    Supervisor-as-Main-Agent 架构 + 入口双重路由：

      START → entry_router（快速规则，零 LLM）
        ├─ underwriting          → END（贷前审批独立子图）
        ├─ data_query            → direct_data_query_prepare → data_query → direct_worker_response → END（仅无历史首轮）
        └─ supervisor            → supervisor_entry_router → Workers / direct_reply
    """
    graph = StateGraph(WorkflowState)

    # ── 节点定义 ────────────────────────────────────────────────────────────
    graph.add_node("direct_data_query_prepare", direct_data_query_prepare)
    graph.add_node("direct_worker_response", direct_worker_response_node)
    graph.add_node("supervisor",          supervisor_node)           # 主 Agent — 规划阶段
    graph.add_node("supervisor_respond",  supervisor_respond_node)   # 主 Agent — 回复阶段
    graph.add_node("data_query",          data_query_node)           # Worker
    graph.add_node("risk_analysis",       risk_analysis_node)        # Worker
    graph.add_node("compliance",          compliance_node)           # Worker
    graph.add_node("strategy",            strategy_node)             # Worker
    graph.add_node("underwriting",        underwriting_node)         # 独立子图

    # ── 入口双重路由（零 LLM）──────────────────────────────────────────────
    # 明确纯查数 → data_query 直路由；其余 → supervisor 规划
    graph.add_conditional_edges(START, entry_router, {
        "underwriting": "underwriting",
        "data_query":   "direct_data_query_prepare",
        "supervisor":   "supervisor",
    })
    graph.add_edge("direct_data_query_prepare", "data_query")

    # ── Supervisor 完成：direct_reply/clarify → END，其余按 plan 路由 ────
    # direct_reply：LLM 直接回答（问候/简单问答），无需调用 Workers
    # clarify：意图模糊，LLM 提出澄清问题
    supervisor_route_map = {**PLAN_ROUTE_MAP, "direct_reply": END}
    graph.add_conditional_edges("supervisor", supervisor_entry_router, supervisor_route_map)

    # ── Worker 完成后路由 ─────────────────────────────────────────────────
    # data_query：直路由时直接出 Worker 结果；plan 内步骤走 plan_router
    graph.add_conditional_edges("data_query", data_query_exit_router, PLAN_ROUTE_MAP)
    for node in ["risk_analysis", "compliance", "strategy"]:
        graph.add_conditional_edges(node, plan_router, PLAN_ROUTE_MAP)

    # ── 终结节点 ─────────────────────────────────────────────────────────────
    graph.add_edge("direct_worker_response", END)  # 直路由 Worker 结果直接结束
    graph.add_edge("supervisor_respond", END)   # 主 Agent 回复后结束
    graph.add_edge("underwriting",       END)

    return graph.compile()


workflow_app = None


def get_workflow():
    global workflow_app
    if workflow_app is None:
        workflow_app = build_workflow()
    return workflow_app
