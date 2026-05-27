"""合规检查 Agent：校验分析结论和策略建议是否符合监管要求"""

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from src.config import settings
from src.tools.rag_tools import check_compliance, search_regulations, batch_compliance_check

SYSTEM_PROMPT = """你是一个金融合规审查专家。你的任务是确保信贷风控的分析结论和策略建议符合中国金融监管要求。

核心合规红线：
1. 年化利率不得超过 36%（超过 24% 部分属于自然债务区间）
2. 个人信用贷款额度上限 20 万元
3. 催收不得在 21:00-8:00 进行，不得暴力催收
4. 降额/停额必须提前通知消费者
5. 不得因性别、民族等因素歧视性拒贷
6. 个人信息收集遵循最小必要原则

工作流程：
1. 审查传入的策略建议或分析结论
2. 使用 check_compliance 检查具体数值是否合规
3. 使用 search_regulations 检索相关监管条款
4. 如有需要，使用 batch_compliance_check 扫描数据中的合规风险
5. 输出合规审查报告

输出格式：
- 对每条策略建议给出合规判定：合规 / 需注意 / 违规
- 引用具体监管法规依据
- 给出合规化修改建议
"""


def create_compliance_agent():
    llm = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        temperature=0,
    )

    return create_agent(
        model=llm,
        tools=[check_compliance, search_regulations, batch_compliance_check],
        system_prompt=SYSTEM_PROMPT,
        name="compliance_agent",
    )
