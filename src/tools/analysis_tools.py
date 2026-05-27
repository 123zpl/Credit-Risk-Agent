"""风险分析工具：多维下钻、对比分析、异常检测"""

import json
import re

from langchain_core.tools import tool

from src.database import execute_readonly_sql

PERIOD_PATTERN = re.compile(r"^\d{4}-\d{2}$")


DRILL_DOWN_DIMENSIONS = {
    "grade": "信用评级",
    "product_type": "产品类型",
    "channel": "获客渠道",
    "purpose": "借款用途",
    "term_months": "贷款期限",
    "overdue_level": "逾期等级",
}

USER_DIMENSIONS = {
    "province": "省份",
    "home_ownership": "房产状况",
    "emp_length": "工作年限",
    "verification_status": "收入验证状态",
}


@tool
def drill_down_overdue_rate(dimension: str) -> str:
    """按指定维度下钻分析逾期率。

    可用维度:
    - 贷款维度: grade(信用评级), product_type(产品类型), channel(获客渠道),
      purpose(借款用途), term_months(贷款期限)
    - 用户维度: province(省份), home_ownership(房产状况), emp_length(工作年限),
      verification_status(收入验证状态)
    """
    all_dims = {**DRILL_DOWN_DIMENSIONS, **USER_DIMENSIONS}
    if dimension not in all_dims:
        return f"不支持的维度: {dimension}，可用维度: {list(all_dims.keys())}"

    dim_label = all_dims[dimension]

    if dimension in USER_DIMENSIONS:
        sql = f"""
            SELECT u.{dimension} AS dim_value,
                   COUNT(*) AS total_loans,
                   SUM(CASE WHEN l.overdue_days > 0 THEN 1 ELSE 0 END) AS overdue_loans,
                   ROUND(SUM(CASE WHEN l.overdue_days > 0 THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) AS overdue_rate_pct,
                   ROUND(AVG(l.loan_amount), 2) AS avg_loan_amount,
                   ROUND(AVG(l.interest_rate), 2) AS avg_interest_rate
            FROM loan_records l
            JOIN user_profiles u ON l.user_id = u.user_id
            GROUP BY u.{dimension}
            ORDER BY overdue_rate_pct DESC
            LIMIT 30
        """
    else:
        sql = f"""
            SELECT {dimension} AS dim_value,
                   COUNT(*) AS total_loans,
                   SUM(CASE WHEN overdue_days > 0 THEN 1 ELSE 0 END) AS overdue_loans,
                   ROUND(SUM(CASE WHEN overdue_days > 0 THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) AS overdue_rate_pct,
                   ROUND(AVG(loan_amount), 2) AS avg_loan_amount,
                   ROUND(AVG(interest_rate), 2) AS avg_interest_rate
            FROM loan_records
            GROUP BY {dimension}
            ORDER BY overdue_rate_pct DESC
            LIMIT 30
        """

    try:
        rows = execute_readonly_sql(sql)
        result = {
            "分析维度": dim_label,
            "维度字段": dimension,
            "分析结果": rows,
        }
        return json.dumps(result, ensure_ascii=False, default=str, indent=2)
    except Exception as e:
        return f"分析失败: {e}"


@tool
def compare_periods(metric: str, period1: str, period2: str) -> str:
    """对比两个时间段的关键指标变化。

    Args:
        metric: 指标名称，可选: overdue_rate(逾期率), loan_volume(放款量),
                avg_amount(平均金额), avg_rate(平均利率)
        period1: 第一个时间段，格式 YYYY-MM (如 2017-01)
        period2: 第二个时间段，格式 YYYY-MM (如 2017-06)
    """
    metric_sql = {
        "overdue_rate": "ROUND(SUM(CASE WHEN overdue_days > 0 THEN 1 ELSE 0 END) / COUNT(*) * 100, 2)",
        "loan_volume": "COUNT(*)",
        "avg_amount": "ROUND(AVG(loan_amount), 2)",
        "avg_rate": "ROUND(AVG(interest_rate), 2)",
    }

    if metric not in metric_sql:
        return f"不支持的指标: {metric}，可选: {list(metric_sql.keys())}"

    if not PERIOD_PATTERN.match(period1) or not PERIOD_PATTERN.match(period2):
        return "时间格式错误，应为 YYYY-MM（如 2017-01）"

    calc = metric_sql[metric]
    sql = f"""
        SELECT
            DATE_FORMAT(issue_date, '%%Y-%%m') AS period,
            {calc} AS value,
            COUNT(*) AS loan_count
        FROM loan_records
        WHERE DATE_FORMAT(issue_date, '%%Y-%%m') IN (:p1, :p2)
        GROUP BY DATE_FORMAT(issue_date, '%%Y-%%m')
        ORDER BY period
    """

    try:
        rows = execute_readonly_sql(sql, {"p1": period1, "p2": period2})
        if len(rows) < 2:
            return f"数据不足，请检查时间段 {period1} 和 {period2} 是否有数据。"

        period_data = {r["period"]: r for r in rows}
        r1 = period_data.get(period1, rows[0])
        r2 = period_data.get(period2, rows[1])
        v1 = float(r1["value"])
        v2 = float(r2["value"])
        change = round(v2 - v1, 2)
        change_pct = round((v2 - v1) / v1 * 100, 2) if v1 != 0 else 0

        result = {
            "指标": metric,
            "时段对比": {
                period1: {"值": v1, "贷款数": r1["loan_count"]},
                period2: {"值": v2, "贷款数": r2["loan_count"]},
            },
            "变化量": change,
            "变化率": f"{change_pct}%",
        }
        return json.dumps(result, ensure_ascii=False, default=str, indent=2)
    except Exception as e:
        return f"对比分析失败: {e}"


PORTRAIT_ALLOWED_FIELDS = {
    "loan_records": [
        "grade", "loan_status", "overdue_level", "product_type",
        "channel", "purpose", "overdue_days", "interest_rate",
        "loan_amount", "term_months",
    ],
    "risk_events": ["event_type", "severity"],
}
PORTRAIT_ALLOWED_OPS = {"=", ">", "<", ">=", "<=", "!="}


@tool
def analyze_user_portrait(field: str, operator: str, value: str) -> str:
    """分析符合特定条件的用户画像特征。使用白名单字段和操作符，安全构建查询。

    Args:
        field: 筛选字段，可选:
            - loan_records 表: grade, loan_status, overdue_level, product_type,
              channel, purpose, overdue_days, interest_rate, loan_amount, term_months
            - risk_events 表: event_type, severity
        operator: 比较操作符，可选: =, >, <, >=, <=, !=
        value: 筛选值，如 "F", "核销", "30", "M3+"
    """
    if operator not in PORTRAIT_ALLOWED_OPS:
        return f"不支持的操作符: {operator}，可选: {sorted(PORTRAIT_ALLOWED_OPS)}"

    target_table = None
    for table, fields in PORTRAIT_ALLOWED_FIELDS.items():
        if field in fields:
            target_table = table
            break
    if target_table is None:
        all_fields = [f for fs in PORTRAIT_ALLOWED_FIELDS.values() for f in fs]
        return f"不支持的字段: {field}，可选: {all_fields}"

    condition_label = f"{field} {operator} {value}"

    if target_table == "loan_records":
        join_clause = "JOIN loan_records l ON u.user_id = l.user_id"
        where_clause = f"l.{field} {operator} :filter_val"
    else:
        join_clause = (
            "JOIN loan_records l ON u.user_id = l.user_id "
            "JOIN risk_events re ON l.loan_id = re.loan_id"
        )
        where_clause = f"re.{field} {operator} :filter_val"

    sql = f"""
        SELECT
            ROUND(AVG(u.annual_income), 0) AS avg_income,
            ROUND(AVG(u.dti), 2) AS avg_dti,
            ROUND(AVG(u.fico_score_low), 0) AS avg_fico,
            ROUND(AVG(u.inq_last_6mths), 1) AS avg_inquiries,
            ROUND(AVG(u.revol_util), 1) AS avg_revol_util,
            ROUND(AVG(u.delinq_2yrs), 1) AS avg_past_delinq,
            COUNT(*) AS total_count
        FROM user_profiles u
        {join_clause}
        WHERE {where_clause}
    """

    try:
        rows = execute_readonly_sql(sql, {"filter_val": value})
        if not rows or rows[0]["total_count"] == 0:
            return f"没有符合条件 [{condition_label}] 的数据。"

        top_home = execute_readonly_sql(f"""
            SELECT u.home_ownership, COUNT(*) as cnt FROM user_profiles u
            {join_clause} WHERE {where_clause}
            GROUP BY u.home_ownership ORDER BY cnt DESC LIMIT 1
        """, {"filter_val": value})

        top_prov = execute_readonly_sql(f"""
            SELECT u.province, COUNT(*) as cnt FROM user_profiles u
            {join_clause} WHERE {where_clause}
            GROUP BY u.province ORDER BY cnt DESC LIMIT 1
        """, {"filter_val": value})

        portrait = rows[0]
        portrait["top_home_ownership"] = top_home[0]["home_ownership"] if top_home else "未知"
        portrait["top_province"] = top_prov[0]["province"] if top_prov else "未知"

        return json.dumps(
            {"筛选条件": condition_label, "用户画像": portrait},
            ensure_ascii=False, default=str, indent=2,
        )
    except Exception as e:
        return f"画像分析失败: {e}"
