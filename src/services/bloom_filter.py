"""
布隆过滤器（Bloom Filter）— 基于 Redis Bitmap 的纯 Python 实现

业务背景
--------
防止「缓存穿透」：攻击者用随机/不存在的 ID 反复请求，导致每次都穿透缓存
直接打到 MySQL，造成数据库压力。

防护接口
--------
  GET /sessions/{session_id}/logs   → bloom:session_ids
  GET /reports/{report_id}          → bloom:report_ids
  GET /applicants/{applicant_id}    → bloom:applicant_ids

原理
----
Bloom Filter 是一种概率型数据结构：
  - add(item)      → 将 item 的 k 个哈希位置置 1
  - contains(item) → 若所有 k 个哈希位置均为 1 → 「可能存在」(允许通过)
                     若任意一位为 0             → 「一定不存在」(直接拒绝)
  - 无误判：不存在的一定返回 False（不存在）
  - 有误判：存在的极少数情况可能返回 True（实际不存在），称为假阳性

参数选取（针对 ≤10 万条记录）
----------------------------
  NUM_BITS   = 1_000_000  (1M bit = 125 KB per filter)
  NUM_HASHES = 7
  → 理论假阳性率 ≈ 0.8%，即 1000 个不存在的 ID 中约 8 个能穿透（可接受）

--------------
「使用布隆过滤器/存放空值拦截非法请求」→ 本文件实现布隆过滤器部分
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

from src.database import redis_client

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ── 过滤器参数 ──────────────────────────────────────────────────────────────
NUM_BITS   = 1_000_000   # 每个过滤器占用的 bit 数 (Redis bitmap)
NUM_HASHES = 7           # 哈希函数数量（7 为 1M bits / 10w 元素时的最优值）
BITMAP_TTL = 86400 * 30  # 30 天，防止 key 永久占用内存

# ── 三个独立过滤器的 Redis key ───────────────────────────────────────────────
KEY_SESSION   = "bloom:session_ids"
KEY_REPORT    = "bloom:report_ids"
KEY_APPLICANT = "bloom:applicant_ids"


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------

def _bit_positions(item: str) -> list[int]:
    """
    使用 k 个不同 seed 的 MD5 哈希，计算 item 对应的 k 个 bit 位置。
    不依赖任何第三方哈希库，只用标准库 hashlib。
    """
    positions = []
    for seed in range(NUM_HASHES):
        # seed 混入 item，保证每轮哈希值独立
        digest = hashlib.md5(f"{seed}:{item}".encode("utf-8")).hexdigest()
        pos = int(digest, 16) % NUM_BITS
        positions.append(pos)
    return positions


# ---------------------------------------------------------------------------
# 核心操作
# ---------------------------------------------------------------------------

def bloom_add(filter_key: str, item: str) -> None:
    """
    将 item 加入布隆过滤器。
    使用 Redis pipeline 批量执行 SETBIT，减少网络往返。
    """
    try:
        pipe = redis_client.pipeline(transaction=False)
        for pos in _bit_positions(item):
            pipe.setbit(filter_key, pos, 1)
        pipe.expire(filter_key, BITMAP_TTL)
        pipe.execute()
    except Exception as e:
        # Redis 异常时静默失败，不影响写入主流程
        logger.warning(f"[BloomFilter] add failed (key={filter_key}): {e}")


def bloom_contains(filter_key: str, item: str) -> bool:
    """
    检查 item 是否「可能」存在于过滤器中。

    返回 False → 一定不存在 → 可安全拒绝，返回 404，无需查 DB
    返回 True  → 可能存在  → 继续走正常 DB 查询逻辑
    """
    try:
        pipe = redis_client.pipeline(transaction=False)
        for pos in _bit_positions(item):
            pipe.getbit(filter_key, pos)
        results = pipe.execute()
        # 所有位均为 1 才认为「可能存在」
        return all(results)
    except Exception as e:
        # Redis 异常时放行（降级：宁可多打一次 DB 也不误拒合法请求）
        logger.warning(f"[BloomFilter] contains check failed (allow): {e}")
        return True


# ---------------------------------------------------------------------------
# 便捷方法（对外暴露）
# ---------------------------------------------------------------------------

def register_session(session_id: str) -> None:
    bloom_add(KEY_SESSION, session_id)


def register_report(report_id: str) -> None:
    bloom_add(KEY_REPORT, report_id)


def register_applicant(applicant_id: str) -> None:
    bloom_add(KEY_APPLICANT, applicant_id)


def check_session(session_id: str) -> bool:
    """True = 可能存在；False = 一定不存在"""
    return bloom_contains(KEY_SESSION, session_id)


def check_report(report_id: str) -> bool:
    return bloom_contains(KEY_REPORT, report_id)


def check_applicant(applicant_id: str) -> bool:
    return bloom_contains(KEY_APPLICANT, applicant_id)


# ---------------------------------------------------------------------------
# 启动预热：从 MySQL 加载已有 ID → 写入过滤器
# ---------------------------------------------------------------------------

def warmup_bloom_filters() -> dict[str, int]:
    """
    系统启动时调用，将 MySQL 中已存在的 ID 批量写入布隆过滤器。
    防止重启后过滤器为空导致合法请求被误拒。

    返回各过滤器写入数量，供日志打印。
    """
    from src.tools.sql_tools import execute_readonly_sql

    counts: dict[str, int] = {"sessions": 0, "reports": 0, "applicants": 0}

    # ── 预热 session_ids（来自 analysis_reports 的 session_id 列）──
    try:
        rows = execute_readonly_sql(
            "SELECT DISTINCT session_id FROM analysis_reports LIMIT 50000", {}
        )
        for r in rows:
            sid = r.get("session_id")
            if sid:
                bloom_add(KEY_SESSION, sid)
                counts["sessions"] += 1
    except Exception as e:
        logger.warning(f"[BloomFilter] warmup sessions failed: {e}")

    # ── 预热 report_ids ──
    try:
        rows = execute_readonly_sql(
            "SELECT report_id FROM analysis_reports LIMIT 50000", {}
        )
        for r in rows:
            rid = r.get("report_id")
            if rid:
                bloom_add(KEY_REPORT, rid)
                counts["reports"] += 1
    except Exception as e:
        logger.warning(f"[BloomFilter] warmup reports failed: {e}")

    # ── 预热 applicant_ids ──
    try:
        rows = execute_readonly_sql(
            "SELECT applicant_id FROM applicants LIMIT 50000", {}
        )
        for r in rows:
            aid = r.get("applicant_id")
            if aid:
                bloom_add(KEY_APPLICANT, aid)
                counts["applicants"] += 1
    except Exception as e:
        logger.warning(f"[BloomFilter] warmup applicants failed: {e}")

    logger.info(
        f"[BloomFilter] Warmup complete — "
        f"sessions={counts['sessions']}, "
        f"reports={counts['reports']}, "
        f"applicants={counts['applicants']}"
    )
    return counts
