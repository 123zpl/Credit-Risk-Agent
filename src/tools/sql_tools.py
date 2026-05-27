"""数据查询工具：安全执行只读 SQL 并返回结构化结果"""

import json
import time
import hashlib

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.database import execute_readonly_sql, redis_client
from src.services.sql_validator import validate_sql
from src.services.sql_validation_cache import is_sql_validated, mark_sql_validated


SCHEMA_INFO = """
数据库表结构如下：

1. user_profiles (用户画像表):
   - user_id: VARCHAR(32), 主键
   - annual_income: DECIMAL, 年收入
   - emp_title: VARCHAR(100), 职业
   - emp_length: VARCHAR(20), 工作年限
   - home_ownership: VARCHAR(20), 房产状况 (RENT/OWN/MORTGAGE/OTHER)
   - province: VARCHAR(50), 省份
   - city: VARCHAR(50), 城市
   - verification_status: VARCHAR(30), 收入验证状态
   - fico_score_low/high: INT, FICO信用评分
   - latest_fico_low/high: INT, 最近FICO评分
   - delinq_2yrs: INT, 近2年逾期次数
   - inq_last_6mths: INT, 近6月信用查询次数
   - open_acc: INT, 活跃信用账户数
   - total_acc: INT, 总信用账户数
   - pub_rec: INT, 公共不良记录数
   - revol_bal: DECIMAL, 循环贷款余额
   - revol_util: DECIMAL, 信用使用率(%)
   - dti: DECIMAL, 负债收入比(%)

2. loan_records (贷款记录表):
   - loan_id: VARCHAR(32), 主键
   - user_id: VARCHAR(32), 用户ID (外键关联 user_profiles)
   - product_type: VARCHAR(20), 产品类型 (花呗/借呗/网商贷)
   - loan_amount: DECIMAL, 借款金额
   - funded_amount: DECIMAL, 实际放款金额
   - term_months: INT, 贷款期限(月) (36或60)
   - interest_rate: DECIMAL, 利率(%)
   - installment: DECIMAL, 每月还款额
   - grade: CHAR(1), 信用评级 (A-G, A最好G最差)
   - sub_grade: VARCHAR(5), 信用子评级
   - purpose: VARCHAR(50), 借款用途 (债务整合/信用卡还款/家庭装修/大额消费/小微经营/购车/医疗/教育/其他)
   - channel: VARCHAR(50), 获客渠道 (支付宝推荐/淘宝入口/线下扫码/短信邀请/APP首页/朋友推荐/搜索引擎/社交媒体)
   - loan_status: VARCHAR(30), 贷款状态 (已结清/正常还款/宽限期/逾期16-30天/逾期31-120天/违约/核销)
   - overdue_days: INT, 逾期天数
   - overdue_level: VARCHAR(10), 逾期等级 (M0/M1/M2/M3/M3+)
   - total_payment: DECIMAL, 累计还款总额
   - total_principal: DECIMAL, 累计还本金
   - total_interest: DECIMAL, 累计还利息
   - total_late_fee: DECIMAL, 累计滞纳金
   - outstanding_principal: DECIMAL, 未还本金
   - recoveries: DECIMAL, 催收回收金额
   - issue_date: DATE, 放款日期
   - last_payment_date: DATE, 最后还款日期
   - last_payment_amount: DECIMAL, 最后还款金额

3. risk_events (风险事件表):
   - event_id: BIGINT, 主键
   - user_id: VARCHAR(32), 用户ID
   - loan_id: VARCHAR(32), 贷款ID
   - event_type: VARCHAR(50), 事件类型 (逾期/多头借贷/信用分下降/异常行为)
   - severity: ENUM (LOW/MEDIUM/HIGH/CRITICAL), 严重程度
   - description: TEXT, 事件描述
   - event_date: DATE, 事件日期
"""

MAX_ROWS = 200
CACHE_TTL = 300  # 缓存5分钟


def _cache_key(sql: str) -> str:
    return "sql_cache:" + hashlib.md5(sql.encode()).hexdigest()


class SqlPlanInput(BaseModel):
    """generate_sql 工具的结构化 SQL 计划"""
    sql: str = Field(
        description=(
            "完整的 MySQL SELECT 语句。"
            "多维度对比必须用 GROUP BY 合并为一条 SQL。"
        )
    )
    tables_used: list[str] = Field(
        description=(
            "SQL 中实际引用的表名列表，必须与 FROM/JOIN 一致。"
            "允许的值: user_profiles, loan_records, risk_events"
        )
    )
    expected_columns: list[str] = Field(
        description="预期返回的结果列名（别名），如 ['grade', 'overdue_rate_pct']"
    )
    explanation: str = Field(
        description="这条 SQL 要回答什么问题（一句话）"
    )


class ExecuteSqlInput(BaseModel):
    sql: str = Field(
        description=(
            "已通过 generate_sql 校验的 SQL，必须与 generate_sql 中提交的 sql 完全一致。"
            "禁止未经 generate_sql 校验直接调用本工具。"
        )
    )


@tool("generate_sql", args_schema=SqlPlanInput)
def generate_sql(
    sql: str,
    tables_used: list[str],
    expected_columns: list[str],
    explanation: str,
) -> str:
    """提交结构化 SQL 计划并进行合规校验（不执行查询）。

    适用场景：在 execute_sql 之前，必须先调用本工具提交 SQL 计划。
    不适用：不需要查库的问题。

    校验项：
    - 只允许 SELECT/WITH
    - 表白名单（user_profiles / loan_records / risk_events）
    - tables_used 与 SQL 中 FROM/JOIN 一致
    - 禁止写操作关键字

    返回：
    - 校验通过 → 提示调用 execute_sql（传入相同 sql）
    - 校验失败 → 具体错误列表，修正后重新调用 generate_sql

    示例1 — 单一指标（各评级逾期率）：
      get_schema_info()  ← 必须先调用
      generate_sql(
        sql="SELECT grade, COUNT(*) AS total, ROUND(SUM(overdue_level != 'M0') / COUNT(*) * 100, 2) AS overdue_rate_pct FROM loan_records GROUP BY grade ORDER BY grade",
        tables_used=["loan_records"],
        expected_columns=["grade", "total", "overdue_rate_pct"],
        explanation="按信用评级统计逾期率"
      )

    示例2 — 多产品对比（一条 SQL，禁止拆分）：
      generate_sql(
        sql="SELECT product_type, COUNT(*) AS total, ROUND(SUM(overdue_level != 'M0') / COUNT(*) * 100, 2) AS overdue_rate_pct FROM loan_records WHERE product_type IN ('花呗','借呗') GROUP BY product_type",
        tables_used=["loan_records"],
        expected_columns=["product_type", "total", "overdue_rate_pct"],
        explanation="对比花呗与借呗逾期率"
      )

    示例3 — 跨表 JOIN：
      generate_sql(
        sql="SELECT CASE WHEN u.annual_income >= 100000 THEN '高收入' ELSE '低收入' END AS income_group, COUNT(*) AS total, ROUND(SUM(l.overdue_level != 'M0') / COUNT(*) * 100, 2) AS overdue_rate_pct FROM loan_records l JOIN user_profiles u ON l.user_id = u.user_id GROUP BY income_group",
        tables_used=["loan_records", "user_profiles"],
        expected_columns=["income_group", "total", "overdue_rate_pct"],
        explanation="按收入水平对比逾期率"
      )

    ❌ 错误：跳过 get_schema_info 直接 generate_sql
    ❌ 错误：generate_sql 校验失败后仍调用 execute_sql
    """
    result = validate_sql(sql, tables_used=tables_used)
    if not result.ok:
        err_text = "\n".join(f"  - {e}" for e in result.errors)
        return (
            f"SQL 校验失败，尚未执行查询。请修正后重新调用 generate_sql：\n{err_text}"
        )

    mark_sql_validated(result.normalized_sql)
    cols = ", ".join(expected_columns) if expected_columns else "（未声明）"
    tables = ", ".join(result.tables_detected)
    return (
        f"SQL 校验通过 ✓\n"
        f"说明: {explanation}\n"
        f"涉及表: {tables}\n"
        f"预期列: {cols}\n\n"
        f"请立即调用 execute_sql，传入与上面完全相同的 sql 参数执行查询。"
    )


@tool("execute_sql", args_schema=ExecuteSqlInput)
def execute_sql(sql: str) -> str:
    """执行已通过 generate_sql 校验的 SQL，返回 JSON 格式行数据。

    适用场景：generate_sql 返回「校验通过 ✓」后，用完全相同的 sql 参数调用本工具。
    不适用：未经 generate_sql 校验的 SQL（会被拒绝）。

    标准流程：get_schema_info → generate_sql → execute_sql（禁止跳过 generate_sql）

    返回格式：
    - 成功："返回 N 条记录 (耗时 Xms)\n[{...}, ...]"
    - 未校验："错误：请先调用 generate_sql 并通过校验"
    - 校验失败："SQL二次校验失败: ..."
    - 执行失败："SQL执行错误: ..."

    示例（承接 generate_sql 示例1）：
      execute_sql(sql="SELECT grade, COUNT(*) AS total, ... FROM loan_records GROUP BY grade ORDER BY grade")
    """
    if not is_sql_validated(sql):
        return (
            "错误：此 SQL 尚未通过 generate_sql 校验。"
            "请先调用 generate_sql 提交 SQL 计划，校验通过后再调用 execute_sql。"
        )

    revalidate = validate_sql(sql)
    if not revalidate.ok:
        err_text = "\n".join(revalidate.errors)
        return f"SQL 二次校验失败，拒绝执行: {err_text}"

    sql = revalidate.normalized_sql
    cache_key = _cache_key(sql)
    cached = redis_client.get(cache_key)
    if cached:
        return f"[缓存命中]\n{cached}"

    if "LIMIT" not in sql.upper():
        sql = sql.rstrip(";") + f" LIMIT {MAX_ROWS}"

    start = time.time()
    try:
        rows = execute_readonly_sql(sql)
        elapsed_ms = int((time.time() - start) * 1000)
    except ValueError as e:
        return f"SQL安全检查失败: {e}"
    except Exception as e:
        return f"SQL执行错误: {e}\n请检查SQL语法后重试。"

    if not rows:
        return "查询结果为空，没有匹配的数据。"

    result = json.dumps(rows, ensure_ascii=False, default=str)
    summary = f"返回 {len(rows)} 条记录 (耗时 {elapsed_ms}ms)"

    try:
        redis_client.setex(cache_key, CACHE_TTL, result)
    except Exception:
        pass

    if len(result) > 5000:
        return f"{summary}\n(数据较多，仅展示前10条)\n{json.dumps(rows[:10], ensure_ascii=False, default=str, indent=2)}"

    return f"{summary}\n{result}"


@tool
def get_schema_info() -> str:
    """获取信贷数据库的完整表结构（表名、字段名、字段类型、字段含义）。

    适用场景：每次数据查询任务的第 1 步，写 SQL 前必须调用，确认字段名与表关系。
    不适用：generate_sql 或 execute_sql 之后重复调用。

    返回格式：纯文本，包含 user_profiles / loan_records / risk_events 三张表的完整字段说明。
    每个任务必须调用且只调用 1 次。"""
    return SCHEMA_INFO


@tool
def get_table_stats() -> str:
    """获取各表的数据量统计和关键业务指标概览（各表行数、贷款状态分布、信用评级分布）。

    适用场景：需要快速了解数据全貌，或用户问"总体情况"类问题时。
    不适用：已有具体查询目标时，直接用 execute_sql 更精准。

    返回格式：JSON 对象，包含 user_profiles/loan_records/risk_events 行数、
    loan_status_distribution（按状态分组的数量+余额）、grade_distribution（按评级的数量+平均利率）。"""
    stats = {}
    try:
        tables = ["user_profiles", "loan_records", "risk_events"]
        for table in tables:
            rows = execute_readonly_sql(f"SELECT COUNT(*) as cnt FROM {table}")
            stats[table] = rows[0]["cnt"]

        status_dist = execute_readonly_sql(
            "SELECT loan_status, COUNT(*) as cnt, "
            "ROUND(SUM(outstanding_principal), 2) as total_balance "
            "FROM loan_records GROUP BY loan_status ORDER BY cnt DESC"
        )
        stats["loan_status_distribution"] = status_dist

        grade_dist = execute_readonly_sql(
            "SELECT grade, COUNT(*) as cnt, "
            "ROUND(AVG(interest_rate), 2) as avg_rate "
            "FROM loan_records GROUP BY grade ORDER BY grade"
        )
        stats["grade_distribution"] = grade_dist

    except Exception as e:
        return f"获取统计信息失败: {e}"

    return json.dumps(stats, ensure_ascii=False, default=str, indent=2)
