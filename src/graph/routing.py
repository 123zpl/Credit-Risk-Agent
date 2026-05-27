"""Legacy 路由 re-export — 主图已使用 entry_router + plan_router，勿接入 build_workflow()。"""

from src.graph.legacy_routing import (
    INTENT_LABELS,
    route_after_compliance,
    route_after_data_query,
    route_after_risk_analysis,
    route_after_router,
    route_after_strategy,
)

__all__ = [
    "INTENT_LABELS",
    "route_after_router",
    "route_after_data_query",
    "route_after_risk_analysis",
    "route_after_compliance",
    "route_after_strategy",
]
