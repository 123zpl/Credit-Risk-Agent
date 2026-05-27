"""SQL 校验层 — generate_sql 通过后、execute_sql 执行前的合规检查。

双层护栏：
  1. 正则层 — 注释剥离、关键字黑名单、多语句、FROM/JOIN 快速抽表（兜底）
  2. AST 层 — sqlglot 解析，结构级禁止 DML/DDL，子查询/CTE 内表名提取（主路径）
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.services.sql_ast_guard import extract_tables_ast, validate_ast_readonly

# 表白名单 + 字段白名单（与 sql_tools.SCHEMA_INFO 保持一致）
ALLOWED_SCHEMA: dict[str, frozenset[str]] = {
    "user_profiles": frozenset({
        "user_id", "annual_income", "emp_title", "emp_length", "home_ownership",
        "province", "city", "verification_status", "fico_score_low", "fico_score_high",
        "latest_fico_low", "latest_fico_high", "delinq_2yrs", "inq_last_6mths",
        "open_acc", "total_acc", "pub_rec", "revol_bal", "revol_util", "dti",
    }),
    "loan_records": frozenset({
        "loan_id", "user_id", "product_type", "loan_amount", "funded_amount",
        "term_months", "interest_rate", "installment", "grade", "sub_grade",
        "purpose", "channel", "loan_status", "overdue_days", "overdue_level",
        "total_payment", "total_principal", "total_interest", "total_late_fee",
        "outstanding_principal", "recoveries", "issue_date", "last_payment_date",
        "last_payment_amount",
    }),
    "risk_events": frozenset({
        "event_id", "user_id", "loan_id", "event_type", "severity",
        "description", "event_date",
    }),
}

ALLOWED_TABLES = frozenset(ALLOWED_SCHEMA.keys())

FORBIDDEN_KEYWORDS = frozenset({
    "INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE", "ALTER", "CREATE",
    "REPLACE", "GRANT", "REVOKE", "EXEC", "EXECUTE", "CALL", "LOAD", "INTO",
    "OUTFILE", "DUMPFILE", "LOCK", "UNLOCK", "SET", "SHOW", "DESCRIBE", "DESC",
})

# FROM / JOIN 后的表名（忽略 schema 前缀 db.table）
_TABLE_REF_RE = re.compile(
    r"\b(?:FROM|JOIN)\s+`?(\w+)`?",
    re.IGNORECASE,
)


@dataclass
class SqlValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    normalized_sql: str = ""
    tables_detected: list[str] = field(default_factory=list)


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql


def _extract_table_names_regex(sql: str) -> list[str]:
    """正则从 FROM/JOIN 抽表名（AST 不可用时的兜底）。"""
    cleaned = _strip_comments(sql)
    seen: set[str] = set()
    tables: list[str] = []
    for match in _TABLE_REF_RE.finditer(cleaned):
        name = match.group(1).lower()
        if name not in seen:
            seen.add(name)
            tables.append(name)
    return tables


def extract_table_names(sql: str) -> list[str]:
    """从 SQL 提取物理表名：优先 AST，失败则回退正则。"""
    ast_tables, ast_errors = extract_tables_ast(_strip_comments(sql.strip().rstrip(";")))
    if not ast_errors and ast_tables:
        return ast_tables
    if not ast_errors and not ast_tables:
        # 合法但无表引用（如 SELECT 1）— 保持空列表
        return []
    return _extract_table_names_regex(sql)


def validate_sql(
    sql: str,
    *,
    tables_used: list[str] | None = None,
) -> SqlValidationResult:
    """
    校验 SQL 是否符合只读查询规范。

    检查项：
    1. 非空、仅 SELECT/WITH（正则）
    2. 禁止写操作关键字（正则）
    3. 禁止多语句（正则 + AST）
    4. AST 结构级只读校验
    5. 表名白名单（AST 抽表，正则兜底）
    6. tables_used 与 SQL 中实际引用表一致（若提供）
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not sql or not sql.strip():
        return SqlValidationResult(ok=False, errors=["SQL 不能为空"])

    normalized = sql.strip().rstrip(";")
    cleaned = _strip_comments(normalized)
    upper = cleaned.upper()

    # 1. 只允许 SELECT / WITH
    stripped_upper = upper.lstrip("(").strip()
    if not (stripped_upper.startswith("SELECT") or stripped_upper.startswith("WITH")):
        errors.append("只允许 SELECT 或 WITH 开头的只读查询")

    # 2. 禁止多语句
    if ";" in normalized:
        errors.append("不允许多条 SQL 语句（请去掉分号）")

    # 3. 禁止危险关键字（粗粒度，覆盖常见写操作）
    tokens = set(re.findall(r"\b[A-Z_]+\b", upper))
    hit = sorted(tokens & FORBIDDEN_KEYWORDS)
    if hit:
        errors.append(f"SQL 包含禁止关键字: {', '.join(hit)}")

    # 4. AST 结构级只读校验（解析失败则记录错误，表名改由正则兜底）
    ast_errors = validate_ast_readonly(cleaned)
    errors.extend(ast_errors)

    # 5. 表名白名单（AST 优先，见 extract_table_names）
    tables_detected = extract_table_names(normalized)
    if ast_errors and not tables_detected:
        tables_detected = _extract_table_names_regex(normalized)
    if not tables_detected:
        errors.append("未能识别查询涉及的表，请检查 FROM/JOIN 子句")
    else:
        unknown = [t for t in tables_detected if t not in ALLOWED_TABLES]
        if unknown:
            errors.append(
                f"使用了未授权的表: {', '.join(unknown)}。"
                f"允许的表: {', '.join(sorted(ALLOWED_TABLES))}"
            )

    # 6. 声明的 tables_used 与实际 SQL 一致
    if tables_used is not None:
        declared = sorted({t.lower().strip() for t in tables_used if t.strip()})
        detected = sorted(set(tables_detected))
        if sorted(declared) != detected:
            errors.append(
                f"tables_used 与 SQL 实际引用不一致: "
                f"声明={declared}, 实际={detected}"
            )

    return SqlValidationResult(
        ok=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        normalized_sql=normalized,
        tables_detected=tables_detected,
    )
