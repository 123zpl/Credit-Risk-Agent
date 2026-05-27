"""聚合健康检查：MySQL、Redis、Milvus、LangSmith 追踪状态"""

from src.config import settings
from src.database import check_connections


def check_milvus() -> bool:
    try:
        from pymilvus import connections, utility

        alias = "health_check"
        connections.connect(
            alias=alias,
            host=settings.milvus_host,
            port=str(settings.milvus_port),
        )
        utility.list_collections(using=alias)
        connections.disconnect(alias)
        return True
    except Exception:
        return False


def check_credit_policy_milvus() -> bool:
    try:
        from pymilvus import connections, utility

        alias = "health_check_policy"
        connections.connect(
            alias=alias,
            host=settings.milvus_host,
            port=str(settings.milvus_port),
            timeout=3,
        )
        ok = utility.has_collection(settings.credit_policy_collection, using=alias)
        connections.disconnect(alias)
        return bool(ok)
    except Exception:
        return False


def check_langsmith_tracing() -> bool:
    try:
        from langsmith import utils

        return bool(utils.tracing_is_enabled())
    except Exception:
        return False


def full_health() -> dict:
    conn = check_connections()
    milvus = check_milvus()
    credit_policy_milvus = check_credit_policy_milvus()
    tracing = check_langsmith_tracing()

    mysql_ok = conn["mysql"]
    redis_ok = conn["redis"]
    core_ok = mysql_ok and redis_ok

    status = "healthy" if core_ok and milvus else "degraded"
    if not core_ok:
        status = "degraded"

    details = None
    if not core_ok:
        details = conn

    return {
        "status": status,
        "mysql": mysql_ok,
        "redis": redis_ok,
        "milvus": milvus,
        "credit_policy_milvus": credit_policy_milvus,
        "langsmith_tracing": tracing,
        "langsmith_node_tracing": settings.langsmith_node_tracing,
        "details": details,
    }
