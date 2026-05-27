"""
Supervisor 主 Agent — 负责规划、调度与最终对客回复。

本模块包含两个节点函数，共同构成"大堂经理"角色：

  supervisor_node（主节点）
    - 读取完整 messages 历史
    - LLM 自由决策：
        * 问候/简单问答 → 直接回复（不调用任何工具，1次 LLM，intent=direct_reply）
        * 需要分析      → 调用 create_analysis_plan 工具，生成执行计划（intent=supervisor）
    - LLM 有自主权，不再强制输出结构化 JSON

  supervisor_respond_node（汇总节点）
    - Workers 全部完成后才调用
    - 收集所有 Worker 的结构化中间结果
    - 结合完整对话历史，用统一语气生成最终自然语言回复

工具定义：
  create_analysis_plan — Supervisor 在需要调用专家 Agent 时主动调用此工具，
                         传入步骤列表和各步骤检查单。

Worker Agent 节点（data_query / risk_analysis / strategy / compliance）
扮演"后厨"角色，只向 state 写入结构化中间结果，绝不直接写 final_report。
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Literal

from langchain_core.messages import SystemMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field, ValidationError

from src.graph.plan_constants import WORKER_STEPS

logger = logging.getLogger(__name__)

SUPERVISOR_UNAVAILABLE_MSG = (
    "抱歉，当前分析服务繁忙，请稍后重试或简化您的问题。"
)

_CLARIFICATION_RE = re.compile(
    r"请问|能否补充|请提供|请说明|哪个|哪类|什么时间|需要了解|澄清|具体指|麻烦告知|能否说明",
    re.IGNORECASE,
)


# ── 分析计划工具的输入 Schema ──────────────────────────────────────────────────
class AnalysisPlanInput(BaseModel):
    """create_analysis_plan 工具的参数 schema"""
    steps: list[Literal["data_query", "risk_analysis", "compliance", "strategy"]] = Field(
        description=(
            "按执行顺序排列的步骤列表。"
            "依赖关系：data_query → risk_analysis → strategy，compliance 可在任意后置。"
        )
    )
    task_instructions: dict[str, str] = Field(
        description=(
            "各步骤的精准任务描述（检查单），key 为步骤名称，value 为具体任务说明。"
            "要具体到数据维度、时间范围、分析目标。"
        )
    )


@tool("create_analysis_plan", args_schema=AnalysisPlanInput)
def create_analysis_plan(
    steps: list[str],
    task_instructions: dict[str, str],
) -> str:
    """
    当用户需要进行信贷风控数据分析时调用此工具，生成分析执行计划。

    适用场景（需要调用此工具）：
    - 数据查询：逾期率、贷款数量、用户画像等指标查询
    - 风险归因：分析风险指标变化原因、下钻特定群体
    - 合规审查：检查利率、策略是否符合监管要求
    - 策略建议：生成可执行的风控策略
    - 复合分析：上述任意组合

    不适用场景（直接回复即可，不要调用此工具）：
    - 问候、寒暄、介绍自己
    - 询问系统能力/帮助信息
    - 不需要查询数据库就能回答的问题
    """
    return json.dumps(
        {"status": "accepted", "steps": steps, "tasks": task_instructions},
        ensure_ascii=False,
    )


# ── Supervisor 主节点 System Prompt ───────────────────────────────────────────
SUPERVISOR_SYSTEM = """你是信贷风控分析平台的资深风控助理，同时也是整个分析团队的总调度。

你有一个强大的工具：create_analysis_plan
- 当用户提出任何需要查询数据、分析风险、生成策略或合规审查的请求时，调用此工具
- 工具会触发后台专家团队（数据专家、风险专家、策略专家、合规专家）并行/串行执行
- 你只需要规划"做什么"和"怎么做"，专家团队会把结果返回给你，你再汇总回复用户

不需要调用工具的情况：
- 用户问候（你好、在吗等）→ 直接友好回复，介绍自己的能力
- 用户问你能做什么 → 直接回复
- 其他不需要查数据就能回答的问题 → 直接回复

调用工具时的规划原则：
1. steps 按执行顺序排列，满足依赖：data_query → risk_analysis → strategy，compliance 可在任意后置
2. task_instructions 要具体：写清楚数据维度、时间范围、分析目标
3. 复合需求拆分为多步骤

【安全与边界 — 必须遵守】
- 不得执行或规划任何写库、改额度、审批通过/拒绝等越权操作；仅做只读分析与建议
- 用户问题超出信贷风控分析范围 → 礼貌说明能力边界，不要调用 create_analysis_plan
- 意图模糊且缺少关键参数（时间范围、产品、地区等）→ 直接追问澄清，不要调用 create_analysis_plan
- 若不确定是否需要查库 → 优先澄清，而非猜测"""


def _get_supervisor_llm():
    """延迟初始化 Supervisor LLM，绑定分析计划工具（便于测试 mock）"""
    from langchain_openai import ChatOpenAI
    from src.config import settings

    llm = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        temperature=0,
    )
    return llm.bind_tools([create_analysis_plan])


def _parse_tool_args(raw_args) -> dict:
    """解析 LLM tool_call args，兼容 JSON 字符串与非 dict 类型。"""
    if isinstance(raw_args, str):
        try:
            raw_args = json.loads(raw_args)
        except json.JSONDecodeError:
            logger.warning("[Supervisor] tool_call args 非合法 JSON 字符串")
            return {}
    return raw_args if isinstance(raw_args, dict) else {}


def _normalize_plan(
    steps: list,
    task_instructions: dict,
    user_query: str,
) -> tuple[list[str], dict[str, str]]:
    """校验并规范化 Supervisor 规划步骤，过滤非法 step。"""
    try:
        validated = AnalysisPlanInput.model_validate({
            "steps": steps or ["data_query"],
            "task_instructions": task_instructions or {},
        })
        steps = list(validated.steps)
        task_instructions = dict(validated.task_instructions)
    except ValidationError:
        logger.warning("[Supervisor] AnalysisPlanInput 校验失败，降级 data_query")
        steps = ["data_query"]
        task_instructions = {}

    steps = [s for s in steps if s in WORKER_STEPS] or ["data_query"]
    task_instructions = {k: v for k, v in task_instructions.items() if k in steps}
    for step in steps:
        task_instructions.setdefault(step, user_query)
    return steps, task_instructions


def _looks_like_clarification(text: str) -> bool:
    """无 tool_call 的回复是否像在向用户追问澄清。"""
    t = (text or "").strip()
    if not t:
        return False
    if _CLARIFICATION_RE.search(t):
        return True
    if ("?" in t or "？" in t) and re.search(
        r"哪个|哪类|哪些|补充|明确|具体",
        t,
        re.IGNORECASE,
    ):
        return True
    return False


def _supervisor_terminal_response(
    state,
    *,
    intent: str,
    report: str,
    action: str,
    log_result: str,
    elapsed_ms: int,
) -> dict:
    """Supervisor 直接结束路径：写入 final_report 并返回 state 增量。"""
    from src.services.log_service import persist_report

    persist_report(
        session_id=state.session_id,
        query=state.user_query,
        intent=intent,
        report=report,
        data_result="",
        risk_result="",
        strategy_result="",
        compliance_result="",
    )
    return {
        "intent": intent,
        "final_report": report,
        "execution_log": [{
            "agent": "supervisor",
            "step": 0,
            "action": action,
            "result": log_result,
            "latency_ms": elapsed_ms,
        }],
    }


def _supervisor_unavailable_response(state, start: float, action: str, reason: str) -> dict:
    elapsed = int((time.time() - start) * 1000)
    logger.warning("[Supervisor] %s: %s", action, reason)
    return _supervisor_terminal_response(
        state,
        intent="direct_reply",
        report=SUPERVISOR_UNAVAILABLE_MSG,
        action=action,
        log_result=reason[:120],
        elapsed_ms=elapsed,
    )


def supervisor_node(state) -> dict:
    """
    Supervisor 主节点 — Tool-Calling 模式。

    LLM 自主决策：
    - 直接回复（问候/简单问答）→ intent=direct_reply，final_report 直接写入，路由到 END
    - 澄清追问 → intent=clarify，final_report 写入，路由到 END
    - 调用 create_analysis_plan  → intent=supervisor，路由到 plan_router → Workers
    """
    from src.services.memory_store import to_langchain_messages

    start = time.time()

    lc_messages = to_langchain_messages(state.messages, state.user_query)
    prompt = [SystemMessage(content=SUPERVISOR_SYSTEM)] + lc_messages

    try:
        llm = _get_supervisor_llm()
        response = llm.invoke(prompt)
    except Exception as e:
        return _supervisor_unavailable_response(
            state, start, "llm_error", f"LLM失败: {e}",
        )

    elapsed = int((time.time() - start) * 1000)

    # ── 检查 LLM 是否调用了 create_analysis_plan 工具 ──────────────────
    tool_calls = getattr(response, "tool_calls", []) or []
    plan_call = next(
        (tc for tc in tool_calls if tc.get("name") == "create_analysis_plan"),
        None,
    )

    if plan_call:
        args = _parse_tool_args(plan_call.get("args", {}))
        steps, task_instructions = _normalize_plan(
            args.get("steps", ["data_query"]),
            args.get("task_instructions", {}),
            state.user_query,
        )

        logger.info(f"[Supervisor] 调用规划工具，steps={steps} ({elapsed}ms)")
        return {
            "intent": "supervisor",
            "execution_plan": steps,
            "task_instructions": task_instructions,
            "plan_index": 0,
            "current_step": 1,
            "execution_log": [{
                "agent": "supervisor",
                "step": 0,
                "action": "plan_tool_call",
                "result": f"规划步骤: {steps}",
                "latency_ms": elapsed,
            }],
        }

    # ── LLM 选择直接回复（问候/简单问答）→ 一次 LLM 完成 ──────────────
    direct_reply = (response.content or "").strip()
    if not direct_reply:
        return _supervisor_unavailable_response(
            state, start, "empty_response", "无 tool_call 且无内容",
        )

    is_clarify = _looks_like_clarification(direct_reply)
    intent = "clarify" if is_clarify else "direct_reply"
    action = "clarify" if is_clarify else "direct_reply"
    logger.info(f"[Supervisor] {action}（无工具调用）({elapsed}ms)")
    return _supervisor_terminal_response(
        state,
        intent=intent,
        report=direct_reply,
        action=action,
        log_result=direct_reply[:100],
        elapsed_ms=elapsed,
    )


# ── Supervisor 回复阶段 System Prompt ─────────────────────────────────────────
SUPERVISOR_RESPOND_SYSTEM = """你是信贷风控分析平台的资深风控助理（主 Agent）。

你的团队（数据查询专家、风险分析专家、策略专家、合规审查专家）刚刚完成了后台分析。
现在你需要扮演"大堂经理"的角色，将后台的分析结果整合为一份专业、温和的最终回复。

回复原则：
1. 用"资深风控助理"的统一语气，始终保持专业而不失温和
2. 结合对话历史，确保回复与上下文连贯（如用户提到了"刚刚那个张三"，你要知道是谁）
3. 绝不暴露内部技术细节（不提"Agent"、"节点"、"SQL"、"工具调用"、模块数量、耗时等词）
4. 数据结论必须有数字支撑，策略建议要具体可操作
5. 若某分析模块未返回有效结果、结果为空或明显失败，优雅说明「因数据/分析限制未能覆盖的部分」，不得编造数字或结论
6. 回复长度与问题复杂度匹配：简单查询给简洁答复，复杂分析给结构化报告"""


def _get_respond_llm():
    """延迟初始化回复 LLM（便于测试 mock）"""
    from langchain_openai import ChatOpenAI
    from src.config import settings

    return ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        temperature=0.3,
    )


def supervisor_respond_node(state) -> dict:
    """
    Supervisor 汇总回复节点 — Workers 全部完成后调用。

    收集所有 Worker 的工具返回结果，结合完整对话历史，
    用统一语气生成最终自然语言回复。
    """
    from langchain_core.messages import HumanMessage
    from src.services.memory_store import to_langchain_messages
    from src.services.log_service import persist_report, persist_execution_log

    start = time.time()

    from src.graph.synthesis_context import build_worker_results_context

    combined = build_worker_results_context(
        data_result=state.data_result,
        risk_result=state.risk_result,
        strategy_result=state.strategy_result,
        compliance_result=state.compliance_result,
    )

    lc_messages = to_langchain_messages(state.messages, state.user_query)
    history_without_last = lc_messages[:-1]

    if combined:
        final_human = HumanMessage(
            content=(
                f"{state.user_query}\n\n"
                f"[内部分析已完成，以下是各专家模块的返回结果，请据此生成最终回复]\n\n"
                f"{combined}"
            )
        )
    else:
        final_human = HumanMessage(content=state.user_query)

    prompt = [SystemMessage(content=SUPERVISOR_RESPOND_SYSTEM)] + history_without_last + [final_human]

    try:
        llm = _get_respond_llm()
        response = llm.invoke(prompt)
        report = response.content
    except Exception as e:
        logger.error(f"[SupervisorRespond] LLM 调用失败: {e}")
        report = "抱歉，生成回复时遇到了问题，请稍后重试。"

    elapsed = int((time.time() - start) * 1000)
    total_latency = sum(log.get("latency_ms", 0) for log in state.execution_log) + elapsed

    persist_report(
        session_id=state.session_id,
        query=state.user_query,
        intent=state.intent,
        report=report,
        data_result=state.data_result,
        risk_result=state.risk_result,
        strategy_result=state.strategy_result,
        compliance_result=state.compliance_result,
    )

    log_entry = {
        "agent": "supervisor_respond",
        "step": state.current_step,
        "action": "final_response_synthesis",
        "result": "最终回复生成完成",
        "latency_ms": elapsed,
        "total_latency_ms": total_latency,
    }

    persist_execution_log(state.session_id, log_entry)

    return {
        "final_report": report,
        "execution_log": [log_entry],
    }
