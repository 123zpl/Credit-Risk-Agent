"""CSV 导出工具 — 将 SQL 查询结果导出为可下载的 CSV 文件。

流程：
  validate_sql（安全校验）→ execute_readonly_sql（全量查询，无 LIMIT）
  → 写 CSV 到 exports/ 目录 → Redis 记录 TTL → 返回下载链接

与 execute_sql 的区别：
  - 不加 LIMIT 限制，导出全量数据（上限 50000 行）
  - 结果写文件，不写 Redis 查询缓存
  - 返回下载 URL 而不是 JSON 数据
"""
from __future__ import annotations

import csv
import io
import logging
import time
import uuid

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.database import execute_readonly_sql, redis_client
from src.services.sql_validator import validate_sql
from src.services.sql_validation_cache import is_sql_validated

logger = logging.getLogger(__name__)

MAX_EXPORT_ROWS = 50_000
EXPORT_TTL = 3600           # 文件有效期 1 小时
EXPORT_DIR = "exports"

# Redis key 前缀，记录哪些 file_id 还在有效期内
_EXPORT_KEY_PREFIX = "export_file:"


def _ensure_export_dir() -> None:
    import os
    os.makedirs(EXPORT_DIR, exist_ok=True)


def _register_export(file_id: str, filepath: str) -> None:
    """在 Redis 里记录导出文件的有效期，TTL 到期后下载接口返回 404。"""
    try:
        redis_client.setex(f"{_EXPORT_KEY_PREFIX}{file_id}", EXPORT_TTL, filepath)
    except Exception as e:
        logger.warning(f"[ExportTool] Redis 记录失败，文件仍可访问: {e}")


def is_export_valid(file_id: str) -> str | None:
    """返回文件路径（有效），或 None（已过期/不存在）。"""
    try:
        val = redis_client.get(f"{_EXPORT_KEY_PREFIX}{file_id}")
        return val if val else None
    except Exception:
        return None


class ExportCsvInput(BaseModel):
    sql: str = Field(
        description=(
            "要导出的 SELECT SQL 语句。"
            "如果用户想导出上一次查询结果，传入上一次 generate_sql 中使用的相同 SQL。"
            "如果用户有新的查询意图，先完成 get_schema_info → generate_sql → execute_sql，"
            "再用相同 SQL 调用本工具。"
        )
    )
    filename_hint: str = Field(
        default="export",
        description="CSV 文件名提示（不含扩展名），如 '逾期率分析'、'高风险用户'",
    )


@tool("export_to_csv", args_schema=ExportCsvInput)
def export_to_csv(sql: str, filename_hint: str = "export") -> str:
    """将 SQL 查询结果导出为 CSV 文件并返回下载链接。

    适用场景：
    - 用户说"导出数据"、"下载"、"要完整数据"、"全部数据"、"给我全量"
    - 用户想保存当前查询结果到本地

    使用规则：
    - 如果本轮已经执行过 generate_sql，直接传入相同的 SQL 调用本工具
    - 如果用户同时有新查询意图，先走 get_schema_info → generate_sql → execute_sql，
      再用相同 SQL 调用 export_to_csv
    - SQL 必须已通过 generate_sql 校验（或本工具内部会重新校验）

    返回：
    - 成功："导出完成，共 N 条记录。[下载CSV](/api/v1/exports/{file_id})"
    - 数据量超限："数据量超过50000条，建议缩小查询范围后重试"
    - 校验失败："SQL 校验失败: ..."
    """
    # ── 安全校验（复用 sql_validator，不依赖内存缓存） ─────────────────────
    result = validate_sql(sql)
    if not result.ok:
        err_text = "; ".join(result.errors)
        return f"SQL 校验失败，无法导出: {err_text}"

    normalized_sql = result.normalized_sql

    # ── 全量查询（不加 LIMIT） ─────────────────────────────────────────────
    start = time.time()
    try:
        rows = execute_readonly_sql(normalized_sql)
    except Exception as e:
        return f"查询执行失败: {e}"

    elapsed_ms = int((time.time() - start) * 1000)

    if not rows:
        return "查询结果为空，没有可导出的数据。"

    if len(rows) > MAX_EXPORT_ROWS:
        return (
            f"数据量超过 {MAX_EXPORT_ROWS:,} 条（实际约 {len(rows):,} 条），"
            f"建议在 SQL 中增加 WHERE 条件缩小范围后重试。"
        )

    # ── 写 CSV ─────────────────────────────────────────────────────────────
    _ensure_export_dir()
    file_id = uuid.uuid4().hex
    safe_hint = "".join(c for c in filename_hint if c.isalnum() or c in "-_\u4e00-\u9fff") or "export"
    filepath = f"{EXPORT_DIR}/{file_id}.csv"

    try:
        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
    except Exception as e:
        return f"写入文件失败: {e}"

    # ── Redis 记录有效期 ────────────────────────────────────────────────────
    _register_export(file_id, filepath)

    logger.info(f"[ExportTool] 导出完成: {len(rows)} 条, {elapsed_ms}ms, file_id={file_id}")

    return (
        f"导出完成，共 **{len(rows):,}** 条记录（查询耗时 {elapsed_ms}ms）。\n\n"
        f"[点击下载 CSV](/api/v1/exports/{file_id})\n\n"
        f"> 下载链接有效期 1 小时，过期后需重新导出。"
    )
