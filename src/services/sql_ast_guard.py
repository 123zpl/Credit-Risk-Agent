"""SQL AST 护栏 — 基于 sqlglot 的结构级只读校验与表名提取。

与 sql_validator 中的正则层配合：
  - 正则：注释剥离、关键字黑名单、多语句、快速前缀检查
  - AST：语法解析、禁止 DML/DDL 节点、子查询/CTE 内表名提取
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

_MYSQL_DIALECT = "mysql"

# AST 层禁止出现的语句/表达式类型（写操作与 DDL）
_FORBIDDEN_EXPR_TYPES: tuple[type, ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.TruncateTable,
    exp.Create,
    exp.Alter,
    exp.Merge,
    exp.Command,  # SHOW / DESCRIBE 等
)

# 允许的顶层语句类型（只读）
_ALLOWED_ROOT_TYPES: tuple[type, ...] = (
    exp.Select,
    exp.Union,
    exp.Intersect,
    exp.Except,
    exp.With,
    exp.Subquery,  # 括号包裹的 SELECT
)


def _root_selectable(root: exp.Expression) -> exp.Expression | None:
    """若 root 代表只读查询，返回其 Select/Union 主体；否则 None。"""
    if isinstance(root, exp.With):
        # WITH 后必须能落到 Select/Union
        inner = root.this
        if isinstance(inner, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
            return inner
        return None
    if isinstance(root, _ALLOWED_ROOT_TYPES):
        return root
    return None


def _collect_cte_names(tree: exp.Expression) -> set[str]:
    names: set[str] = set()
    for cte in tree.find_all(exp.CTE):
        alias = cte.alias
        if alias:
            names.add(alias.lower())
    return names


def extract_tables_ast(sql: str) -> tuple[list[str], list[str]]:
    """
    从 SQL AST 提取物理表名（含子查询、JOIN、CTE 内层），排除 CTE 别名。

    Returns:
        (tables_in_order, errors) — 解析失败时 tables 为空
    """
    errors: list[str] = []
    try:
        statements = sqlglot.parse(sql, dialect=_MYSQL_DIALECT)
    except Exception as exc:
        return [], [f"SQL 语法解析失败: {exc}"]

    if not statements:
        return [], ["SQL 语法解析失败: 空语句"]
    if len(statements) > 1:
        return [], ["SQL 语法解析失败: 检测到多条语句"]

    root = statements[0]
    if _root_selectable(root) is None:
        return [], ["SQL 语法解析失败: 非只读查询结构"]

    cte_names = _collect_cte_names(root)
    seen: set[str] = set()
    tables: list[str] = []

    for table in root.find_all(exp.Table):
        name = (table.name or "").strip().lower()
        if not name or name in cte_names:
            continue
        if name not in seen:
            seen.add(name)
            tables.append(name)

    return tables, errors


def validate_ast_readonly(sql: str) -> list[str]:
    """
    结构级只读校验。返回错误列表（空 = 通过）。
    """
    errors: list[str] = []
    try:
        statements = sqlglot.parse(sql, dialect=_MYSQL_DIALECT)
    except Exception as exc:
        return [f"SQL 语法解析失败: {exc}"]

    if not statements:
        return ["SQL 语法解析失败: 空语句"]
    if len(statements) > 1:
        return ["AST 检测到多条语句，仅允许单条 SELECT"]

    root = statements[0]

    for forbidden_type in _FORBIDDEN_EXPR_TYPES:
        if root.find(forbidden_type):
            errors.append(f"AST 检测到禁止的操作: {forbidden_type.__name__}")

    if _root_selectable(root) is None:
        errors.append("AST 仅允许 SELECT / WITH / UNION 等只读查询")

    # WITH 内每个 CTE 也必须是只读
    if isinstance(root, exp.With):
        for cte in root.find_all(exp.CTE):
            inner = cte.this
            if inner and not isinstance(
                inner, (exp.Select, exp.Union, exp.Intersect, exp.Except, exp.Subquery)
            ):
                errors.append("CTE 内仅允许只读子查询")

    return errors
