"""策略建议 Agent：基于分析结果生成可执行的风控策略"""

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from src.config import settings
from src.tools.analysis_tools import analyze_user_portrait

SYSTEM_PROMPT = """你是一个信贷风控策略专家。你的任务是基于风险分析结果，生成可执行的风控策略建议。

策略生成原则：
1. 每条策略必须有明确的触发条件（用字段+阈值表示）
2. 每条策略必须有明确的执行动作（拒绝/降额/人工审核/监控）
3. 必须评估策略的预期影响（拦截量、减少坏账、损失收入）
4. 策略要分级，不能一刀切

【查数约束】
- 禁止自定义 SQL；如需补充群体画像，仅使用 analyze_user_portrait（白名单字段与操作符）
- 优先基于上游风险分析结果与已有数据下结论；工具无法覆盖时说明限制

可用的执行动作：
- REJECT: 拒绝申请
- REDUCE_LIMIT: 降低授信额度
- MANUAL_REVIEW: 转人工审核
- MONITOR: 加入重点监控名单
- INCREASE_RATE: 提高利率（风险定价）

输出格式（JSON）：
{
    "策略名称": "xxx",
    "触发条件": {"字段": "阈值"},
    "执行动作": "REJECT/REDUCE_LIMIT/...",
    "动作参数": {},
    "预估影响": {
        "预计影响贷款数": 0,
        "预计减少坏账金额": 0,
        "预计损失收入": 0
    },
    "优先级": "HIGH/MEDIUM/LOW",
    "需要合规审查": true/false
}

【工具失败兜底】
- 若工具返回以「失败」「错误」「不支持」开头或含 error 字段，不得虚构数据
- 明确标注「因数据/工具限制无法完成的部分」，只基于已成功工具结果下结论"""

STRATEGY_TOOLS = [analyze_user_portrait]


def create_strategy_agent():
    llm = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        temperature=0.1,
    )

    return create_agent(
        model=llm,
        tools=STRATEGY_TOOLS,
        system_prompt=SYSTEM_PROMPT,
        name="strategy_agent",
    )
