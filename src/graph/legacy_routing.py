"""Legacy 意图路由函数 — 旧 Router 架构专用，主图已切换为 entry_router + supervisor。

保留供单元测试与历史参考；勿接入 build_workflow()。
"""

INTENT_LABELS = ("chitchat", "data_query", "risk_analysis", "compliance", "strategy", "underwriting")

_ROUTER_TARGETS = {
    "chitchat": "chat",
    "data_query": "data_query",
    "risk_analysis": "data_query",
    "compliance": "data_query",
    "strategy": "data_query",
    "underwriting": "underwriting",
}


def route_after_router(intent: str) -> str:
    """Router 之后的第一跳节点。"""
    return _ROUTER_TARGETS.get(intent, "data_query")


def route_after_data_query(intent: str) -> str:
    """DataQuery 完成后的下一节点（Legacy）。"""
    if intent == "data_query":
        return "end"
    if intent == "compliance":
        return "compliance"
    return "risk_analysis"


def route_after_risk_analysis(intent: str) -> str:
    """RiskAnalysis 完成后（Legacy）。"""
    if intent == "strategy":
        return "strategy"
    return "end"


def route_after_compliance(intent: str) -> str:
    """Compliance 完成后（Legacy）。"""
    if intent == "strategy":
        return "report"
    return "end"


def route_after_strategy(_intent: str) -> str:
    """Strategy 完成后必须过合规审查（Legacy）。"""
    return "compliance"
