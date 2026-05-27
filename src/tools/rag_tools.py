"""合规知识库 RAG 工具：硬规则引擎 + Milvus 语义检索双通道"""

import json
import logging

from langchain_core.tools import tool

from src.config import settings
from src.infra.rag_search import search_milvus

logger = logging.getLogger(__name__)

COMPLIANCE_RULES = {
    "interest_rate_cap": {
        "name": "利率上限",
        "rule": "年化利率不得超过36%（对应月利率3%）",
        "source": "《最高人民法院关于审理民间借贷案件适用法律若干问题的规定》",
        "threshold": 36.0,
        "check_field": "interest_rate",
        "description": "超过年化24%的部分为自然债务区间，超过36%的部分无效",
    },
    "loan_amount_limit": {
        "name": "单笔限额",
        "rule": "个人网络借贷金额上限20万元",
        "source": "《网络借贷信息中介机构业务活动管理暂行办法》",
        "threshold": 200000,
        "check_field": "loan_amount",
    },
    "collection_hours": {
        "name": "催收时间限制",
        "rule": "催收不得在每日21:00至次日8:00进行",
        "source": "《互联网金融逾期债务催收自律公约》",
    },
    "data_privacy": {
        "name": "数据隐私保护",
        "rule": "收集个人信息应遵循最小必要原则，处理个人信息应取得个人同意",
        "source": "《个人信息保护法》第六条、第十三条",
    },
    "consumer_notification": {
        "name": "消费者告知义务",
        "rule": "降低信用额度应提前通知消费者，不得未经告知直接降额",
        "source": "《消费者权益保护法》第八条、第二十六条",
    },
    "fair_lending": {
        "name": "公平信贷",
        "rule": "不得因性别、民族、宗教等因素歧视性拒贷或差异化定价",
        "source": "《商业银行法》第五条",
    },
}


def _keyword_search(query: str) -> list[dict]:
    """关键词兜底搜索（Milvus 不可用时使用）"""
    keywords = query.split()
    results = []

    for _rule_key, rule in COMPLIANCE_RULES.items():
        searchable = rule["name"] + rule["rule"] + rule.get("description", "")
        if any(kw in searchable for kw in keywords):
            results.append({
                "类型": "合规规则",
                "名称": rule["name"],
                "内容": rule["rule"],
                "来源": rule["source"],
            })

    return results


@tool
def check_compliance(check_type: str, value: float = 0) -> str:
    """检查特定指标是否符合监管要求。"""
    if check_type not in COMPLIANCE_RULES:
        return f"不支持的检查类型: {check_type}，可选: {list(COMPLIANCE_RULES.keys())}"

    rule = COMPLIANCE_RULES[check_type]
    result = {
        "检查项": rule["name"],
        "监管依据": rule["source"],
        "规则说明": rule["rule"],
    }

    if "threshold" in rule:
        is_compliant = value <= rule["threshold"]
        result["检查值"] = value
        result["阈值"] = rule["threshold"]
        result["合规状态"] = "合规" if is_compliant else "违规"
        if not is_compliant:
            result["风险提示"] = f"当前值 {value} 超过监管上限 {rule['threshold']}"
    else:
        result["合规状态"] = "需人工确认"
        result["建议"] = "此项需要结合具体业务操作进行人工审查"

    return json.dumps(result, ensure_ascii=False, indent=2)


@tool
def search_regulations(query: str) -> str:
    """搜索监管法规知识库。优先使用 Milvus 语义检索，不可用时降级为关键词匹配。"""
    hits = search_milvus(settings.milvus_collection, query, top_k=5)

    if hits:
        output = {"检索方式": "语义检索(Milvus)", "相关法规条款": hits}
    else:
        keyword_results = _keyword_search(query)
        if keyword_results:
            output = {"检索方式": "关键词匹配", "相关法规条款": keyword_results}
        else:
            return f"未找到与 '{query}' 直接相关的监管条款。建议拆分关键词重试，或咨询合规团队。"

    return json.dumps(output, ensure_ascii=False, indent=2)


@tool
def batch_compliance_check() -> str:
    """批量检查当前贷款数据中的合规风险点，扫描利率越线和额度越线情况。"""
    from src.database import execute_readonly_sql

    try:
        checks = []

        rate_violations = execute_readonly_sql("""
            SELECT grade, COUNT(*) as cnt,
                   ROUND(MAX(interest_rate), 2) as max_rate,
                   ROUND(AVG(interest_rate), 2) as avg_rate
            FROM loan_records
            WHERE interest_rate > 36
            GROUP BY grade ORDER BY max_rate DESC
        """)
        checks.append({
            "检查项": "利率超36%红线",
            "违规记录数": sum(r["cnt"] for r in rate_violations) if rate_violations else 0,
            "详情": rate_violations if rate_violations else "无违规",
        })

        amount_violations = execute_readonly_sql("""
            SELECT product_type, COUNT(*) as cnt,
                   ROUND(MAX(loan_amount), 2) as max_amount
            FROM loan_records
            WHERE loan_amount > 200000
            GROUP BY product_type ORDER BY max_amount DESC
        """)
        checks.append({
            "检查项": "个人贷款超20万限额",
            "违规记录数": sum(r["cnt"] for r in amount_violations) if amount_violations else 0,
            "详情": amount_violations if amount_violations else "无违规",
        })

        high_dti = execute_readonly_sql("""
            SELECT COUNT(*) as cnt FROM user_profiles WHERE dti > 50
        """)
        checks.append({
            "检查项": "负债收入比超50%高风险用户",
            "数量": high_dti[0]["cnt"] if high_dti else 0,
            "建议": "关注这部分用户的还款能力",
        })

        return json.dumps(checks, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("[batch_compliance_check] 扫描失败: %s", e)
        return json.dumps(
            {
                "error": f"批量合规扫描失败: {e}",
                "建议": "请稍后重试或改用 check_compliance 单项检查",
            },
            ensure_ascii=False,
        )
