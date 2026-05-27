"""Applicant generation service for underwriting flow."""

from __future__ import annotations

import random
import uuid
from decimal import Decimal

from sqlalchemy import text

from src.database import execute_readonly_sql, get_db

PRODUCT_WEIGHTS = (
    ("花呗", 0.5),
    ("借呗", 0.35),
    ("网商贷", 0.15),
)

CHANNELS = ["APP首页", "支付宝推荐", "短信邀请", "朋友推荐", "搜索引擎"]
PURPOSES = ["债务整合", "信用卡还款", "家庭装修", "购车", "医疗", "教育", "其他"]

# ── 中文映射 ────────────────────────────────────────────────────────────────

HOME_OWNERSHIP_CN: dict[str, str] = {
    "OWN":      "自有住房",
    "MORTGAGE": "按揭住房",
    "RENT":     "租房",
    "NONE":     "无住房",
    "OTHER":    "其他",
    "ANY":      "其他",
}

EMP_LENGTH_CN: dict[str, str] = {
    "< 1 year":  "1年以下",
    "1 year":    "1年",
    "2 years":   "2年",
    "3 years":   "3年",
    "4 years":   "4年",
    "5 years":   "5年",
    "6 years":   "6年",
    "7 years":   "7年",
    "8 years":   "8年",
    "9 years":   "9年",
    "10+ years": "10年以上",
}

# 当职业字段为英文或空时，从此列表随机选取
CHINESE_EMP_TITLES = [
    "软件工程师", "产品经理", "数据分析师", "市场专员", "销售经理",
    "财务会计", "运营专员", "人力资源", "行政文员", "客服专员",
    "教师", "医生", "护士", "律师", "设计师",
    "司机", "厨师", "餐饮服务员", "快递员", "保安",
    "个体经营者", "自由职业者", "工厂工人", "建筑工人", "农业从业者",
    "银行职员", "保险代理人", "电商运营", "短视频创作者", "直播带货",
]

FORM_EMP_LENGTHS = ["1年以下", "1年", "2年", "3年", "4年", "5年", "6年", "7年", "8年", "9年", "10年以上"]
FORM_HOME_OWNERSHIPS = ["自有住房", "按揭住房", "租房", "无住房", "其他"]
FORM_EMP_TITLES = CHINESE_EMP_TITLES[:20]
FORM_TERMS = [12, 24, 36]
FORM_LOCATIONS: dict[str, list[str]] = {
    "广东省": ["广州市", "深圳市", "东莞市", "佛山市"],
    "上海市": ["上海市"],
    "北京市": ["北京市"],
    "浙江省": ["杭州市", "宁波市", "温州市"],
    "江苏省": ["南京市", "苏州市", "无锡市"],
    "四川省": ["成都市", "绵阳市"],
    "湖北省": ["武汉市"],
    "山东省": ["济南市", "青岛市"],
    "福建省": ["福州市", "厦门市"],
    "其他": ["其他"],
}

# ── 标准化辅助函数 ──────────────────────────────────────────────────────────

def _normalize_home_ownership(raw: str) -> str:
    """将英文 home_ownership 映射为中文；已是中文则原样返回。"""
    v = str(raw or "").strip().upper()
    return HOME_OWNERSHIP_CN.get(v, raw if raw and not raw.isascii() else "其他")


def _normalize_emp_length(raw: str) -> str:
    """将 '3 years' 格式映射为中文；已是中文则原样返回。"""
    v = str(raw or "").strip()
    if v in EMP_LENGTH_CN:
        return EMP_LENGTH_CN[v]
    # 尝试忽略大小写匹配
    for k, cn in EMP_LENGTH_CN.items():
        if k.lower() == v.lower():
            return cn
    # 若已是中文或含有中文数字，原样返回
    if v and not v.isascii():
        return v
    return "不详"


def _normalize_emp_title(raw: str, rand: random.Random) -> str:
    """若职业字段是纯 ASCII（英文），随机替换为中文职业；已是中文则原样返回。"""
    v = str(raw or "").strip()
    if not v or v.isascii():
        return rand.choice(CHINESE_EMP_TITLES)
    return v[:100]


def _normalize_location(raw: str, default: str) -> str:
    """省市字段：若是英文或空则用默认值。"""
    v = str(raw or "").strip()
    if not v or v.isascii():
        return default
    return v[:50]


def _build_location(province: str, city: str) -> tuple[str, str]:
    """
    处理省市重复问题（如 province=city='上海市'）：
    - 若 city 与 province 相同，city 置为空字符串
    - 若 city 以 province 开头（如 city='广东省广州市'），去掉前缀
    """
    p = _normalize_location(province, "其他")
    c = _normalize_location(city, "")
    if not c:
        return p, ""
    # 完全相同
    if c == p:
        return p, ""
    # city 包含 province 前缀（如"广东省广州市" -> "广州市"）
    for suffix in (p, p.rstrip("省市区")):
        if c.startswith(suffix) and len(c) > len(suffix):
            c = c[len(suffix):]
            break
    return p, c


def ensure_applicants_table() -> None:
    ddl = """
    CREATE TABLE IF NOT EXISTS applicants (
        applicant_id   VARCHAR(32) PRIMARY KEY,
        name           VARCHAR(50) NOT NULL,
        annual_income  DECIMAL(12,2) NOT NULL,
        emp_title      VARCHAR(100),
        emp_length     VARCHAR(20),
        home_ownership VARCHAR(20),
        province       VARCHAR(50),
        city           VARCHAR(50),
        dti            DECIMAL(5,2),
        fico_score     INT,
        delinq_2yrs    INT DEFAULT 0,
        inq_last_6mths INT DEFAULT 0,
        revol_util     DECIMAL(5,2),
        open_acc       INT,
        total_acc      INT,
        pub_rec        INT DEFAULT 0,
        requested_amount DECIMAL(12,2) NOT NULL,
        requested_term   INT NOT NULL,
        product_type     VARCHAR(20) NOT NULL,
        channel          VARCHAR(50),
        purpose          VARCHAR(50),
        status           VARCHAR(20) DEFAULT 'PENDING',
        approved_amount  DECIMAL(12,2),
        approved_rate    DECIMAL(5,2),
        risk_score       INT,
        risk_grade       VARCHAR(5),
        decision_reason  TEXT,
        approval_report  MEDIUMTEXT COMMENT 'Agent 生成的完整审批报告',
        score_breakdown  TEXT COMMENT 'JSON: 各维度评分明细',
        reviewed_at      DATETIME,
        created_at       DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """
    with get_db() as session:
        session.execute(text(ddl))
    # 兼容旧表：按需补列
    _add_column_if_missing("approval_report", "MEDIUMTEXT")
    _add_column_if_missing("score_breakdown", "TEXT")


def _add_column_if_missing(col: str, col_type: str) -> None:
    try:
        with get_db() as session:
            session.execute(text(f"ALTER TABLE applicants ADD COLUMN {col} {col_type}"))
    except Exception:
        pass  # 列已存在则忽略


FICO_PROFILE_RANGES = {
    "high":   (720, 850),   # 高信用
    "medium": (620, 719),   # 中信用
    "low":    (300, 619),   # 低信用
    "random": (300, 850),   # 随机
}


def _load_profile_samples(limit: int = 5000, fico_profile: str = "random") -> list[dict]:
    fico_min, fico_max = FICO_PROFILE_RANGES.get(fico_profile, (300, 850))
    rows = execute_readonly_sql(
        """
        SELECT annual_income, emp_title, emp_length, home_ownership, province, city,
               dti, fico_score_low, delinq_2yrs, inq_last_6mths, revol_util,
               open_acc, total_acc, pub_rec
        FROM user_profiles
        WHERE annual_income IS NOT NULL AND dti IS NOT NULL AND fico_score_low IS NOT NULL
          AND fico_score_low >= :fmin AND fico_score_low <= :fmax
        ORDER BY RAND()
        LIMIT :lim
        """,
        {"lim": limit, "fmin": fico_min, "fmax": fico_max},
    )
    return rows


def _choice_weighted(rand: random.Random) -> str:
    p = rand.random()
    acc = 0.0
    for value, weight in PRODUCT_WEIGHTS:
        acc += weight
        if p <= acc:
            return value
    return PRODUCT_WEIGHTS[-1][0]


def build_applicant_records(profile_samples: list[dict], count: int = 20, seed: int | None = None) -> list[dict]:
    """Build synthetic applicant records from profile distribution samples."""
    rand = random.Random(seed)
    if not profile_samples:
        profile_samples = [{
            "annual_income": 120000,
            "emp_title": "职员",
            "emp_length": "3年",
            "home_ownership": "租房",
            "province": "广东省",
            "city": "广州市",
            "dti": 25.0,
            "fico_score_low": 680,
            "delinq_2yrs": 0,
            "inq_last_6mths": 2,
            "revol_util": 40.0,
            "open_acc": 8,
            "total_acc": 20,
            "pub_rec": 0,
        }]

    applicants: list[dict] = []
    for _ in range(count):
        src = rand.choice(profile_samples)
        annual_income = max(30000.0, float(src.get("annual_income") or 120000) * rand.uniform(0.8, 1.2))
        dti = min(99.0, max(0.0, float(src.get("dti") or 25.0) + rand.uniform(-6, 6)))
        fico = int(min(850, max(300, int(src.get("fico_score_low") or 680) + rand.randint(-40, 40))))

        requested_amount = round(min(200000.0, max(2000.0, annual_income * rand.uniform(0.1, 0.6))), 2)
        applicant = {
            "applicant_id": "A" + uuid.uuid4().hex[:15],
            "name": f"申请人{uuid.uuid4().hex[:6]}",
            "annual_income": Decimal(str(round(annual_income, 2))),
            "emp_title": _normalize_emp_title(str(src.get("emp_title") or ""), rand),
            "emp_length": _normalize_emp_length(str(src.get("emp_length") or "")),
            "home_ownership": _normalize_home_ownership(str(src.get("home_ownership") or "")),
            **dict(zip(("province", "city"), _build_location(
                str(src.get("province") or ""), str(src.get("city") or "")
            ))),
            "dti": Decimal(str(round(dti, 2))),
            "fico_score": fico,
            "delinq_2yrs": int(src.get("delinq_2yrs") or 0),
            "inq_last_6mths": int(src.get("inq_last_6mths") or 0),
            "revol_util": Decimal(str(round(float(src.get("revol_util") or 0), 2))),
            "open_acc": int(src.get("open_acc") or 0),
            "total_acc": int(src.get("total_acc") or 0),
            "pub_rec": int(src.get("pub_rec") or 0),
            "requested_amount": Decimal(str(requested_amount)),
            "requested_term": rand.choice([12, 24, 36]),
            "product_type": _choice_weighted(rand),
            "channel": rand.choice(CHANNELS),
            "purpose": rand.choice(PURPOSES),
            "status": "PENDING",
        }
        applicants.append(applicant)
    return applicants


def persist_applicants(applicants: list[dict]) -> list[str]:
    """Insert generated applicants into DB."""
    if not applicants:
        return []
    insert_sql = text(
        """
        INSERT INTO applicants (
            applicant_id, name, annual_income, emp_title, emp_length, home_ownership, province, city,
            dti, fico_score, delinq_2yrs, inq_last_6mths, revol_util, open_acc, total_acc, pub_rec,
            requested_amount, requested_term, product_type, channel, purpose, status
        ) VALUES (
            :applicant_id, :name, :annual_income, :emp_title, :emp_length, :home_ownership, :province, :city,
            :dti, :fico_score, :delinq_2yrs, :inq_last_6mths, :revol_util, :open_acc, :total_acc, :pub_rec,
            :requested_amount, :requested_term, :product_type, :channel, :purpose, :status
        )
        """
    )
    with get_db() as session:
        for applicant in applicants:
            session.execute(insert_sql, applicant)
    return [a["applicant_id"] for a in applicants]


def get_form_options() -> dict:
    """Return dropdown options for the user application form."""
    return {
        "product_types": [p[0] for p in PRODUCT_WEIGHTS],
        "channels": list(CHANNELS),
        "purposes": list(PURPOSES),
        "emp_titles": list(FORM_EMP_TITLES),
        "emp_lengths": list(FORM_EMP_LENGTHS),
        "home_ownerships": list(FORM_HOME_OWNERSHIPS),
        "terms": list(FORM_TERMS),
        "locations": dict(FORM_LOCATIONS),
    }


def create_applicant_from_submit(payload) -> dict:
    """Persist a user-submitted applicant record (status=PENDING)."""
    from src.models.applicant_submit_models import ApplicantSubmitRequest

    req = payload if isinstance(payload, ApplicantSubmitRequest) else ApplicantSubmitRequest.model_validate(payload)
    ensure_applicants_table()

    product_types = {p[0] for p in PRODUCT_WEIGHTS}
    if req.product_type not in product_types:
        raise ValueError(f"product_type 无效，可选: {sorted(product_types)}")

    province, city = _build_location(req.province, req.city)
    applicant_id = "A" + uuid.uuid4().hex[:15]
    record = {
        "applicant_id": applicant_id,
        "name": req.name.strip(),
        "annual_income": Decimal(str(round(req.annual_income, 2))),
        "emp_title": req.emp_title.strip()[:100],
        "emp_length": req.emp_length.strip()[:20],
        "home_ownership": req.home_ownership.strip()[:20],
        "province": province,
        "city": city,
        "dti": Decimal(str(round(req.dti, 2))),
        "fico_score": int(req.fico_score),
        "delinq_2yrs": int(req.delinq_2yrs),
        "inq_last_6mths": int(req.inq_last_6mths),
        "revol_util": Decimal(str(round(req.revol_util, 2))),
        "open_acc": int(req.open_acc),
        "total_acc": int(req.total_acc),
        "pub_rec": int(req.pub_rec),
        "requested_amount": Decimal(str(round(req.requested_amount, 2))),
        "requested_term": int(req.requested_term),
        "product_type": req.product_type,
        "channel": req.channel,
        "purpose": req.purpose,
        "status": "PENDING",
    }
    persist_applicants([record])
    return record


def generate_applicants(count: int = 20, seed: int | None = None, fico_profile: str = "random") -> list[str]:
    """Generate applicants and persist to database.

    fico_profile: 'random' | 'high'(≥720) | 'medium'(620-719) | 'low'(<620)
    """
    ensure_applicants_table()
    samples = _load_profile_samples(fico_profile=fico_profile)
    applicants = build_applicant_records(samples, count=count, seed=seed)
    return persist_applicants(applicants)


def get_applicant_count() -> int:
    ensure_applicants_table()
    rows = execute_readonly_sql("SELECT COUNT(*) AS cnt FROM applicants", {})
    return int((rows[0] if rows else {}).get("cnt") or 0)


def ensure_applicants_on_startup(min_count: int = 1, generate_count: int = 20) -> list[str]:
    """Ensure applicants table has seed data for demo/dev usage."""
    if get_applicant_count() >= min_count:
        return []
    return generate_applicants(count=generate_count)
