"""
信贷风控 Agent 数据管道
功能：Lending Club CSV → 抽样 → 清洗 → 中文化 → 导入 MySQL

使用方式:
    # 第1步：下载 Lending Club 数据集
    # 从 https://www.kaggle.com/datasets/wordsforthewise/lending-club 下载
    # 将 accepted_2007_to_2018Q4.csv 放到 data/ 目录下，重命名为 lending_club_raw.csv

    # 第2步：运行此脚本
    python scripts/data_pipeline.py
"""

import hashlib
import random
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

# 将项目根目录加入 path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import settings

# ============================================
# 映射配置
# ============================================

STATE_TO_PROVINCE = {
    "CA": "广东省", "TX": "山东省", "NY": "江苏省", "FL": "浙江省",
    "IL": "河南省", "PA": "四川省", "OH": "湖北省", "GA": "湖南省",
    "NC": "安徽省", "MI": "河北省", "NJ": "福建省", "VA": "上海市",
    "WA": "北京市", "AZ": "辽宁省", "MA": "江西省", "TN": "陕西省",
    "IN": "广西壮族自治区", "MO": "重庆市", "MD": "黑龙江省", "WI": "吉林省",
    "CO": "云南省", "MN": "贵州省", "SC": "山西省", "AL": "内蒙古自治区",
    "LA": "甘肃省", "KY": "海南省", "OR": "新疆维吾尔自治区", "OK": "天津市",
    "CT": "宁夏回族自治区", "UT": "青海省", "IA": "西藏自治区",
    "NV": "深圳市", "AR": "杭州市", "MS": "成都市", "KS": "武汉市",
    "NM": "南京市", "NE": "长沙市", "WV": "合肥市", "ID": "郑州市",
    "HI": "厦门市", "NH": "大连市", "ME": "苏州市", "MT": "无锡市",
    "RI": "宁波市", "DE": "温州市", "SD": "东莞市", "ND": "佛山市",
    "AK": "珠海市", "DC": "青岛市", "VT": "济南市", "WY": "石家庄市",
}

PROVINCE_TO_CITY = {
    "广东省": ["广州市", "深圳市", "东莞市", "佛山市", "珠海市", "惠州市"],
    "江苏省": ["南京市", "苏州市", "无锡市", "常州市", "南通市"],
    "浙江省": ["杭州市", "宁波市", "温州市", "嘉兴市", "绍兴市"],
    "山东省": ["济南市", "青岛市", "烟台市", "潍坊市", "临沂市"],
    "河南省": ["郑州市", "洛阳市", "南阳市", "新乡市"],
    "四川省": ["成都市", "绵阳市", "德阳市", "宜宾市"],
    "湖北省": ["武汉市", "宜昌市", "襄阳市", "荆州市"],
    "湖南省": ["长沙市", "株洲市", "岳阳市", "常德市"],
    "上海市": ["上海市"],
    "北京市": ["北京市"],
    "重庆市": ["重庆市"],
    "天津市": ["天津市"],
}

PURPOSE_MAP = {
    "debt_consolidation": "债务整合",
    "credit_card": "信用卡还款",
    "home_improvement": "家庭装修",
    "other": "其他",
    "major_purchase": "大额消费",
    "small_business": "小微经营",
    "car": "购车",
    "medical": "医疗",
    "moving": "搬家",
    "vacation": "旅游",
    "house": "购房",
    "wedding": "婚礼",
    "renewable_energy": "新能源",
    "educational": "教育",
}

STATUS_MAP = {
    "Fully Paid": "已结清",
    "Current": "正常还款",
    "Charged Off": "核销",
    "Late (31-120 days)": "逾期31-120天",
    "In Grace Period": "宽限期",
    "Late (16-30 days)": "逾期16-30天",
    "Default": "违约",
    "Does not meet the credit policy. Status:Fully Paid": "已结清",
    "Does not meet the credit policy. Status:Charged Off": "核销",
}

CHANNELS = ["支付宝推荐", "淘宝入口", "线下扫码", "短信邀请", "APP首页", "朋友推荐", "搜索引擎", "社交媒体"]

PRODUCT_WEIGHTS = {
    "花呗": 0.5,
    "借呗": 0.35,
    "网商贷": 0.15,
}

# ============================================
# 核心逻辑
# ============================================

SELECTED_COLUMNS = [
    "id", "member_id", "loan_amnt", "funded_amnt", "term", "int_rate",
    "installment", "grade", "sub_grade", "emp_title", "emp_length",
    "home_ownership", "annual_inc", "verification_status", "issue_d",
    "loan_status", "purpose", "addr_state", "dti",
    "delinq_2yrs", "fico_range_low", "fico_range_high",
    "inq_last_6mths", "open_acc", "total_acc", "pub_rec",
    "revol_bal", "revol_util", "last_fico_range_low", "last_fico_range_high",
    "total_pymnt", "total_rec_prncp", "total_rec_int", "total_rec_late_fee",
    "out_prncp", "recoveries", "last_pymnt_d", "last_pymnt_amnt",
]


def load_and_sample(raw_path: str, sample_size: int) -> pd.DataFrame:
    """加载原始 CSV 并分层抽样"""
    print(f"[1/5] 加载原始数据: {raw_path}")
    df = pd.read_csv(raw_path, low_memory=False, usecols=lambda c: c in SELECTED_COLUMNS)
    print(f"  原始数据量: {len(df):,} 条")

    # 过滤掉 loan_status 为空的行
    df = df.dropna(subset=["loan_status"])
    # 只保留已知状态
    df = df[df["loan_status"].isin(STATUS_MAP.keys())]
    print(f"  有效数据量: {len(df):,} 条")

    if len(df) <= sample_size:
        print(f"  数据量 <= {sample_size}，使用全量数据")
        return df

    # 按 loan_status 分层抽样
    print(f"[2/5] 分层抽样 {sample_size:,} 条...")
    sample = df.groupby("loan_status", group_keys=False).apply(
        lambda x: x.sample(
            n=max(1, int(len(x) / len(df) * sample_size)),
            random_state=42,
        )
    )
    print(f"  抽样后数据量: {len(sample):,} 条")
    return sample


def _generate_user_id(row) -> str:
    raw = str(row.get("member_id", "")) + str(row.get("id", ""))
    return "U" + hashlib.md5(raw.encode()).hexdigest()[:15]


def _parse_term(term_str) -> int:
    if pd.isna(term_str):
        return 36
    return int(str(term_str).strip().replace("months", "").strip())


def _parse_rate(rate_str) -> float:
    if pd.isna(rate_str):
        return 0.0
    return float(str(rate_str).strip().replace("%", ""))


def _parse_date(date_str) -> str | None:
    if pd.isna(date_str):
        return None
    try:
        return pd.to_datetime(date_str, format="%b-%Y").strftime("%Y-%m-%d")
    except Exception:
        try:
            return pd.to_datetime(date_str).strftime("%Y-%m-%d")
        except Exception:
            return None


def _parse_emp_length(emp_str) -> str:
    if pd.isna(emp_str):
        return "未知"
    s = str(emp_str).strip()
    if "10+" in s:
        return "10年以上"
    if "< 1" in s:
        return "不到1年"
    return s.replace("years", "年").replace("year", "年").strip()


def _calc_overdue_level(status: str, overdue_days: int) -> str:
    if status in ("已结清", "正常还款"):
        return "M0"
    if status == "宽限期":
        return "M0"
    if overdue_days <= 30:
        return "M1"
    if overdue_days <= 60:
        return "M2"
    if overdue_days <= 90:
        return "M3"
    return "M3+"


def _calc_overdue_days(status: str) -> int:
    if status in ("已结清", "正常还款", "宽限期"):
        return 0
    if status == "逾期16-30天":
        return random.randint(16, 30)
    if status == "逾期31-120天":
        return random.randint(31, 120)
    if status in ("违约", "核销"):
        return random.randint(90, 365)
    return 0


def clean_and_transform(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """清洗、转换、中文化，生成 user_profiles 和 loan_records 两张表的数据"""
    print("[3/5] 数据清洗与中文化...")
    random.seed(42)

    users = []
    loans = []
    seen_users = set()

    for _, row in df.iterrows():
        user_id = _generate_user_id(row)
        loan_id = "L" + hashlib.md5(str(row.get("id", "")).encode()).hexdigest()[:15]

        # 地区映射
        state = str(row.get("addr_state", ""))
        province = STATE_TO_PROVINCE.get(state, "其他")
        city_list = PROVINCE_TO_CITY.get(province, [province])
        city = random.choice(city_list)

        # 产品类型（按权重随机分配）
        product = random.choices(
            list(PRODUCT_WEIGHTS.keys()),
            weights=list(PRODUCT_WEIGHTS.values()),
            k=1,
        )[0]

        # 渠道
        channel = random.choice(CHANNELS)

        # 贷款状态
        raw_status = str(row.get("loan_status", ""))
        loan_status = STATUS_MAP.get(raw_status, raw_status)

        # 逾期天数 & 等级
        overdue_days = _calc_overdue_days(loan_status)
        overdue_level = _calc_overdue_level(loan_status, overdue_days)

        # 用户画像（去重）
        if user_id not in seen_users:
            seen_users.add(user_id)
            users.append({
                "user_id": user_id,
                "annual_income": round(float(row.get("annual_inc", 0) or 0), 2),
                "emp_title": str(row.get("emp_title", ""))[:100] if pd.notna(row.get("emp_title")) else None,
                "emp_length": _parse_emp_length(row.get("emp_length")),
                "home_ownership": str(row.get("home_ownership", "OTHER")),
                "province": province,
                "city": city,
                "verification_status": str(row.get("verification_status", "")),
                "fico_score_low": int(row.get("fico_range_low", 0) or 0),
                "fico_score_high": int(row.get("fico_range_high", 0) or 0),
                "latest_fico_low": int(row.get("last_fico_range_low", 0) or 0),
                "latest_fico_high": int(row.get("last_fico_range_high", 0) or 0),
                "delinq_2yrs": int(row.get("delinq_2yrs", 0) or 0),
                "inq_last_6mths": int(row.get("inq_last_6mths", 0) or 0),
                "open_acc": int(row.get("open_acc", 0) or 0),
                "total_acc": int(row.get("total_acc", 0) or 0),
                "pub_rec": int(row.get("pub_rec", 0) or 0),
                "revol_bal": round(float(row.get("revol_bal", 0) or 0), 2),
                "revol_util": round(float(row.get("revol_util", 0) or 0) if pd.notna(row.get("revol_util")) else 0, 2),
                "dti": round(float(row.get("dti", 0) or 0), 2),
            })

        # 贷款记录
        loans.append({
            "loan_id": loan_id,
            "user_id": user_id,
            "product_type": product,
            "loan_amount": round(float(row.get("loan_amnt", 0) or 0), 2),
            "funded_amount": round(float(row.get("funded_amnt", 0) or 0), 2),
            "term_months": _parse_term(row.get("term")),
            "interest_rate": _parse_rate(row.get("int_rate")),
            "installment": round(float(row.get("installment", 0) or 0), 2),
            "grade": str(row.get("grade", "C"))[:1],
            "sub_grade": str(row.get("sub_grade", "C1"))[:5],
            "purpose": PURPOSE_MAP.get(str(row.get("purpose", "other")), "其他"),
            "channel": channel,
            "loan_status": loan_status,
            "overdue_days": overdue_days,
            "overdue_level": overdue_level,
            "total_payment": round(float(row.get("total_pymnt", 0) or 0), 2),
            "total_principal": round(float(row.get("total_rec_prncp", 0) or 0), 2),
            "total_interest": round(float(row.get("total_rec_int", 0) or 0), 2),
            "total_late_fee": round(float(row.get("total_rec_late_fee", 0) or 0), 2),
            "outstanding_principal": round(float(row.get("out_prncp", 0) or 0), 2),
            "recoveries": round(float(row.get("recoveries", 0) or 0), 2),
            "issue_date": _parse_date(row.get("issue_d")),
            "last_payment_date": _parse_date(row.get("last_pymnt_d")),
            "last_payment_amount": round(float(row.get("last_pymnt_amnt", 0) or 0), 2),
        })

    df_users = pd.DataFrame(users)
    df_loans = pd.DataFrame(loans)

    print(f"  用户画像: {len(df_users):,} 条")
    print(f"  贷款记录: {len(df_loans):,} 条")
    print(f"  贷款状态分布:\n{df_loans['loan_status'].value_counts().to_string()}")

    return df_users, df_loans


def generate_risk_events(df_loans: pd.DataFrame, df_users: pd.DataFrame) -> pd.DataFrame:
    """基于贷款和用户数据生成风险事件"""
    print("[4/5] 生成风险事件数据...")
    random.seed(42)
    events = []

    overdue_loans = df_loans[df_loans["overdue_days"] > 0]
    for _, loan in overdue_loans.iterrows():
        events.append({
            "user_id": loan["user_id"],
            "loan_id": loan["loan_id"],
            "event_type": "逾期",
            "severity": (
                "LOW" if loan["overdue_days"] <= 30
                else "MEDIUM" if loan["overdue_days"] <= 60
                else "HIGH" if loan["overdue_days"] <= 90
                else "CRITICAL"
            ),
            "description": f"贷款{loan['loan_id']}逾期{loan['overdue_days']}天，等级{loan['overdue_level']}",
            "event_date": loan["issue_date"],
        })

    high_inq_users = df_users[df_users["inq_last_6mths"] >= 5]
    for _, user in high_inq_users.iterrows():
        user_loans = df_loans[df_loans["user_id"] == user["user_id"]]
        if not user_loans.empty:
            events.append({
                "user_id": user["user_id"],
                "loan_id": user_loans.iloc[0]["loan_id"],
                "event_type": "多头借贷",
                "severity": "MEDIUM" if user["inq_last_6mths"] < 8 else "HIGH",
                "description": f"用户近6月信用查询{user['inq_last_6mths']}次，疑似多头借贷",
                "event_date": user_loans.iloc[0]["issue_date"],
            })

    fico_drop_users = df_users[
        (df_users["fico_score_low"] > 0)
        & (df_users["latest_fico_low"] > 0)
        & ((df_users["fico_score_low"] - df_users["latest_fico_low"]) >= 50)
    ]
    for _, user in fico_drop_users.iterrows():
        user_loans = df_loans[df_loans["user_id"] == user["user_id"]]
        if not user_loans.empty:
            drop = user["fico_score_low"] - user["latest_fico_low"]
            events.append({
                "user_id": user["user_id"],
                "loan_id": user_loans.iloc[0]["loan_id"],
                "event_type": "信用分下降",
                "severity": "MEDIUM" if drop < 80 else "HIGH",
                "description": f"FICO评分从{user['fico_score_low']}降至{user['latest_fico_low']}，下降{drop}分",
                "event_date": user_loans.iloc[0]["issue_date"],
            })

    df_events = pd.DataFrame(events)
    print(f"  风险事件: {len(df_events):,} 条")
    if not df_events.empty:
        print(f"  事件类型分布:\n{df_events['event_type'].value_counts().to_string()}")
    return df_events


def import_to_mysql(
    df_users: pd.DataFrame,
    df_loans: pd.DataFrame,
    df_events: pd.DataFrame,
):
    """将清洗后的数据导入 MySQL"""
    print("[5/5] 导入 MySQL...")
    engine = create_engine(settings.mysql_url, echo=False)

    with engine.connect() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        conn.execute(text("TRUNCATE TABLE risk_events"))
        conn.execute(text("TRUNCATE TABLE loan_records"))
        conn.execute(text("TRUNCATE TABLE user_profiles"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
        conn.commit()

    batch_size = 5000

    print(f"  导入 user_profiles ({len(df_users):,} 条)...")
    df_users.to_sql("user_profiles", engine, if_exists="append", index=False, method="multi", chunksize=batch_size)

    print(f"  导入 loan_records ({len(df_loans):,} 条)...")
    df_loans.to_sql("loan_records", engine, if_exists="append", index=False, method="multi", chunksize=batch_size)

    if not df_events.empty:
        print(f"  导入 risk_events ({len(df_events):,} 条)...")
        df_events.to_sql("risk_events", engine, if_exists="append", index=False, method="multi", chunksize=batch_size)

    with engine.connect() as conn:
        for table in ["user_profiles", "loan_records", "risk_events"]:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            print(f"  [OK] {table}: {count:,} 条")

    print("\n数据导入完成!")


def run_pipeline():
    raw_path = settings.project_root / settings.data_raw_path

    if not raw_path.exists():
        print(f"错误: 找不到原始数据文件 {raw_path}")
        print("请从 Kaggle 下载 Lending Club 数据集:")
        print("  https://www.kaggle.com/datasets/wordsforthewise/lending-club")
        print(f"将 CSV 文件放到: {raw_path}")
        sys.exit(1)

    df = load_and_sample(str(raw_path), settings.data_sample_size)
    df_users, df_loans = clean_and_transform(df)
    df_events = generate_risk_events(df_loans, df_users)
    import_to_mysql(df_users, df_loans, df_events)

    # 打印数据概览
    print("\n" + "=" * 50)
    print("数据概览")
    print("=" * 50)
    print(f"用户数量:   {len(df_users):,}")
    print(f"贷款数量:   {len(df_loans):,}")
    print(f"风险事件:   {len(df_events):,}")
    print(f"\n贷款状态分布:")
    print(df_loans["loan_status"].value_counts().to_string())
    print(f"\n产品类型分布:")
    print(df_loans["product_type"].value_counts().to_string())
    print(f"\n信用评级分布:")
    print(df_loans["grade"].value_counts().sort_index().to_string())


if __name__ == "__main__":
    run_pipeline()
