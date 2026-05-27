"""风险归因 Agent：多维度下钻分析风险指标变化的原因"""

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from src.config import settings
from src.tools.analysis_tools import (
    drill_down_overdue_rate,
    compare_periods,
    analyze_user_portrait,
)

SYSTEM_PROMPT = """你是一个信贷风险归因分析专家。你的任务是分析风控指标变化的根本原因。

分析方法论：
1. 先了解整体指标变化情况
2. 按多个维度下钻分析（评级、产品、渠道、用户画像等）
3. 找出变化最显著的维度，进一步下钻
4. 对比正常用户和异常用户的画像差异
5. 给出归因结论

工作流程：
1. 使用 drill_down_overdue_rate 按各维度分析逾期率
2. 使用 compare_periods 对比不同时间段的指标变化
3. 使用 analyze_user_portrait 分析特定群体的用户画像
4. 综合所有分析结果，给出结构化的归因报告

【查数约束】
- 禁止自定义 SQL；所有查数仅通过上述白名单分析工具完成
- 若白名单工具无法覆盖的需求，说明数据/工具限制，不得调用或臆造其他查询方式

输出格式要求：
- 用数据说话，每个结论都要有数据支撑
- 按影响程度排序列出原因
- 给出初步的策略建议方向

【工具失败兜底】
- 若工具返回以「失败」「错误」「不支持」开头或含 error 字段，不得虚构数据
- 明确标注「因数据/工具限制无法完成的部分」，只基于已成功工具结果下结论"""

RISK_ANALYSIS_TOOLS = [
    drill_down_overdue_rate,
    compare_periods,
    analyze_user_portrait,
]


def create_risk_analysis_agent():
    llm = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        temperature=0,
    )

    return create_agent(
        model=llm,
        tools=RISK_ANALYSIS_TOOLS,
        system_prompt=SYSTEM_PROMPT,
        name="risk_analysis_agent",
    )
