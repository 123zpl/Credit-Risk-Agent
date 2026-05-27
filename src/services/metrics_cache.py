"""
Redis 指标缓存 — 逻辑过期策略
-------------------------------
原理：Key 永不从 Redis 消失（无 TTL），数据内部携带 expire_at 时间戳。
      请求命中"已逻辑过期"的数据时，立即返回旧数据（不阻塞用户），
      同时通过 Redis SETNX 互斥锁确保只有一个后台线程去异步刷新 MySQL。
      对应 Java 项目中的"热点数据逻辑过期策略 + Redisson 分布式锁"。
"""

import json
import logging
import threading
import time

from src.database import execute_readonly_sql, redis_client

logger = logging.getLogger(__name__)

METRICS_CACHE_KEY = "metrics:dashboard"
METRICS_LOCK_KEY  = "metrics:dashboard:refresh_lock"

# 逻辑过期时长（秒）—— 数据"应该"多久刷一次
LOGICAL_TTL = 300   # 5 分钟

# Redis Key 持久化时长（秒）—— Key 本身在 Redis 里保留多久
# 设置为逻辑过期的 10 倍，保证后台刷新期间 Key 不会真正消失
PHYSICAL_TTL = LOGICAL_TTL * 10

# 刷新锁持有时长（秒），防止刷新线程异常后锁不释放
LOCK_TTL = 20


# ---------------------------------------------------------------------------
# 内部：查 MySQL 计算完整指标
# ---------------------------------------------------------------------------

def _compute_metrics_from_db() -> dict:
    """直接查 MySQL 计算所有风控指标（不涉及缓存层）"""
    metrics: dict = {}
    try:
        summary = execute_readonly_sql("""
            SELECT
                COUNT(*) AS total_loans,
                COUNT(DISTINCT user_id) AS total_users,
                ROUND(SUM(loan_amount), 2) AS total_loan_amount,
                ROUND(SUM(outstanding_principal), 2) AS total_outstanding,
                ROUND(AVG(interest_rate), 2) AS avg_interest_rate,
                ROUND(SUM(CASE WHEN overdue_days > 0 THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) AS overdue_rate_pct,
                ROUND(SUM(CASE WHEN loan_status IN ('违约', '核销') THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) AS bad_rate_pct
            FROM loan_records
        """)
        if summary:
            metrics["summary"] = summary[0]

        status_dist = execute_readonly_sql("""
            SELECT loan_status, COUNT(*) AS cnt
            FROM loan_records
            GROUP BY loan_status ORDER BY cnt DESC
        """)
        metrics["status_distribution"] = {r["loan_status"]: r["cnt"] for r in status_dist}

        grade_dist = execute_readonly_sql("""
            SELECT grade, COUNT(*) AS cnt,
                   ROUND(AVG(interest_rate), 2) AS avg_rate,
                   ROUND(SUM(CASE WHEN overdue_days > 0 THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) AS overdue_rate_pct
            FROM loan_records
            GROUP BY grade ORDER BY grade
        """)
        metrics["grade_distribution"] = grade_dist

        table_counts = {}
        for table in ["user_profiles", "loan_records", "risk_events"]:
            rows = execute_readonly_sql(f"SELECT COUNT(*) as cnt FROM {table}")
            table_counts[table] = rows[0]["cnt"]
        metrics["table_counts"] = table_counts

    except Exception as e:
        logger.warning(f"[metrics_cache] Failed to compute metrics from DB: {e}")

    return metrics


# ---------------------------------------------------------------------------
# 内部：写入 Redis（带逻辑过期时间戳，不设 TTL）
# ---------------------------------------------------------------------------

def _write_to_redis(data: dict) -> None:
    """
    将 {data, expire_at} 写入 Redis。
    Key 本身设置 PHYSICAL_TTL（防止永久占内存），
    但业务层只看 expire_at 字段，不依赖 Key 的 TTL 做过期判断。
    """
    payload = {
        "data":      data,
        "expire_at": time.time() + LOGICAL_TTL,   # 逻辑过期时间戳
    }
    try:
        redis_client.setex(
            METRICS_CACHE_KEY,
            PHYSICAL_TTL,
            json.dumps(payload, ensure_ascii=False, default=str),
        )
        logger.debug("[metrics_cache] Cache refreshed, next logical expire in %ds", LOGICAL_TTL)
    except Exception as e:
        logger.warning(f"[metrics_cache] Failed to write Redis: {e}")


# ---------------------------------------------------------------------------
# 内部：后台线程执行刷新（SETNX 互斥锁，只有一个线程能进入）
# ---------------------------------------------------------------------------

def _async_refresh() -> None:
    """
    尝试获取 Redis 互斥锁（SETNX），抢到才刷新，抢不到直接退出。
    对应 Java 里 Redisson tryLock 的语义。
    """
    # SETNX：SET if Not eXists —— 只有锁不存在时才能设置成功
    acquired = redis_client.set(METRICS_LOCK_KEY, "1", nx=True, ex=LOCK_TTL)
    if not acquired:
        # 其他线程已经在刷新，直接退出，继续用旧数据服务
        logger.debug("[metrics_cache] Refresh lock held by another thread, skip.")
        return

    try:
        logger.info("[metrics_cache] Background refresh started.")
        fresh_data = _compute_metrics_from_db()
        if fresh_data:
            _write_to_redis(fresh_data)
            logger.info("[metrics_cache] Background refresh complete.")
    except Exception as e:
        logger.error(f"[metrics_cache] Background refresh failed: {e}")
    finally:
        # 无论成功失败都要释放锁
        redis_client.delete(METRICS_LOCK_KEY)


# ---------------------------------------------------------------------------
# 公开接口：get_metrics()
# ---------------------------------------------------------------------------

def get_metrics() -> dict:
    """
    逻辑过期版本的缓存读取入口。

    流程：
      1. Redis Key 不存在（冷启动）→ 同步查 MySQL，写缓存，返回
      2. Key 存在且逻辑未过期    → 直接返回缓存数据（_cache=hit）
      3. Key 存在但逻辑已过期    → 立即返回旧数据（_cache=stale），
                                   同时开后台线程异步刷新
    """
    raw = None
    try:
        raw = redis_client.get(METRICS_CACHE_KEY)
    except Exception as e:
        logger.warning(f"[metrics_cache] Redis read error: {e}")

    # ── 冷启动：Key 不存在，同步加载 ──────────────────────────────────
    if raw is None:
        logger.info("[metrics_cache] Cold start, loading from DB synchronously.")
        data = _compute_metrics_from_db()
        if data:
            _write_to_redis(data)
        data["_cache"] = "miss"
        return data

    # ── 反序列化 ───────────────────────────────────────────────────────
    try:
        payload = json.loads(raw)
        data      = payload.get("data", {})
        expire_at = payload.get("expire_at", 0)
    except Exception:
        # 数据损坏，降级为同步查询
        data = _compute_metrics_from_db()
        data["_cache"] = "miss"
        return data

    # ── 逻辑未过期：直接返回 ───────────────────────────────────────────
    if time.time() < expire_at:
        data["_cache"] = "hit"
        return data

    # ── 逻辑已过期：返回旧数据 + 后台异步刷新 ─────────────────────────
    # 用户立即拿到响应，不等待 MySQL 查询
    t = threading.Thread(target=_async_refresh, daemon=True)
    t.start()

    data["_cache"] = "stale"   # 标记为"数据略旧，正在后台刷新"
    return data


# ---------------------------------------------------------------------------
# 兼容旧调用：refresh_metrics() 保留为强制同步刷新（供 /stats?force=true 用）
# ---------------------------------------------------------------------------

def refresh_metrics() -> dict:
    """强制同步刷新缓存（绕过逻辑过期判断），适用于手动刷新场景。"""
    data = _compute_metrics_from_db()
    if data:
        _write_to_redis(data)
    data["_cache"] = "refreshed"
    return data
