-- ============================================
-- 信贷风控 Agent 数据库初始化脚本
-- ============================================

CREATE DATABASE IF NOT EXISTS credit_risk_db
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_unicode_ci;

USE credit_risk_db;

-- -------------------------------------------
-- 1. 用户画像表
-- -------------------------------------------
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id         VARCHAR(32)  PRIMARY KEY COMMENT '用户唯一ID',
    annual_income   DECIMAL(12,2)            COMMENT '年收入',
    emp_title       VARCHAR(100)             COMMENT '职业',
    emp_length      VARCHAR(20)              COMMENT '工作年限',
    home_ownership  VARCHAR(20)              COMMENT '房产状况: RENT/OWN/MORTGAGE/OTHER',
    province        VARCHAR(50)              COMMENT '省份',
    city            VARCHAR(50)              COMMENT '城市',
    verification_status VARCHAR(30)          COMMENT '收入验证状态',
    fico_score_low  INT                      COMMENT 'FICO信用评分(低)',
    fico_score_high INT                      COMMENT 'FICO信用评分(高)',
    latest_fico_low INT                      COMMENT '最近FICO评分(低)',
    latest_fico_high INT                     COMMENT '最近FICO评分(高)',
    delinq_2yrs     INT          DEFAULT 0   COMMENT '近2年逾期次数',
    inq_last_6mths  INT          DEFAULT 0   COMMENT '近6月信用查询次数',
    open_acc        INT          DEFAULT 0   COMMENT '活跃信用账户数',
    total_acc       INT          DEFAULT 0   COMMENT '总信用账户数',
    pub_rec         INT          DEFAULT 0   COMMENT '公共不良记录数',
    revol_bal       DECIMAL(12,2) DEFAULT 0  COMMENT '循环贷款余额',
    revol_util      DECIMAL(5,2)             COMMENT '信用使用率(%)',
    dti             DECIMAL(6,2)             COMMENT '负债收入比(%)',
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_province (province),
    INDEX idx_fico (fico_score_low),
    INDEX idx_dti (dti),
    INDEX idx_income (annual_income)
) ENGINE=InnoDB COMMENT='用户画像表';

-- -------------------------------------------
-- 2. 贷款记录表
-- -------------------------------------------
CREATE TABLE IF NOT EXISTS loan_records (
    loan_id         VARCHAR(32)  PRIMARY KEY COMMENT '贷款唯一ID',
    user_id         VARCHAR(32)  NOT NULL    COMMENT '用户ID',
    product_type    VARCHAR(20)  NOT NULL    COMMENT '产品类型: 花呗/借呗/网商贷',
    loan_amount     DECIMAL(12,2) NOT NULL   COMMENT '借款金额',
    funded_amount   DECIMAL(12,2)            COMMENT '实际放款金额',
    term_months     INT          NOT NULL    COMMENT '贷款期限(月)',
    interest_rate   DECIMAL(5,2) NOT NULL    COMMENT '利率(%)',
    installment     DECIMAL(10,2)            COMMENT '每月还款额',
    grade           CHAR(1)      NOT NULL    COMMENT '信用评级: A-G',
    sub_grade       VARCHAR(5)               COMMENT '信用子评级: A1-G5',
    purpose         VARCHAR(50)              COMMENT '借款用途',
    channel         VARCHAR(50)              COMMENT '获客渠道',
    loan_status     VARCHAR(30)  NOT NULL    COMMENT '贷款状态',
    overdue_days    INT          DEFAULT 0   COMMENT '逾期天数',
    overdue_level   VARCHAR(10)              COMMENT '逾期等级: M0/M1/M2/M3/M3+',
    total_payment   DECIMAL(12,2) DEFAULT 0  COMMENT '累计还款总额',
    total_principal DECIMAL(12,2) DEFAULT 0  COMMENT '累计还本金',
    total_interest  DECIMAL(12,2) DEFAULT 0  COMMENT '累计还利息',
    total_late_fee  DECIMAL(10,2) DEFAULT 0  COMMENT '累计滞纳金',
    outstanding_principal DECIMAL(12,2) DEFAULT 0 COMMENT '未还本金',
    recoveries      DECIMAL(10,2) DEFAULT 0  COMMENT '催收回收金额',
    issue_date      DATE         NOT NULL    COMMENT '放款日期',
    last_payment_date DATE                   COMMENT '最后还款日期',
    last_payment_amount DECIMAL(10,2)        COMMENT '最后还款金额',
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_status (loan_status),
    INDEX idx_grade (grade),
    INDEX idx_issue_date (issue_date),
    INDEX idx_product (product_type),
    INDEX idx_channel (channel),
    INDEX idx_overdue (overdue_level),
    FOREIGN KEY (user_id) REFERENCES user_profiles(user_id)
) ENGINE=InnoDB COMMENT='贷款记录表';

-- -------------------------------------------
-- 3. 风险事件表
-- -------------------------------------------
CREATE TABLE IF NOT EXISTS risk_events (
    event_id        BIGINT       AUTO_INCREMENT PRIMARY KEY,
    user_id         VARCHAR(32)  NOT NULL    COMMENT '用户ID',
    loan_id         VARCHAR(32)              COMMENT '关联贷款ID',
    event_type      VARCHAR(50)  NOT NULL    COMMENT '事件类型: 逾期/多头借贷/信用分下降/异常行为',
    severity        ENUM('LOW','MEDIUM','HIGH','CRITICAL') COMMENT '严重程度',
    description     TEXT                     COMMENT '事件描述',
    event_date      DATE         NOT NULL    COMMENT '事件日期',
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user (user_id),
    INDEX idx_type (event_type),
    INDEX idx_date (event_date),
    INDEX idx_severity (severity)
) ENGINE=InnoDB COMMENT='风险事件表';

-- -------------------------------------------
-- 4. Agent 执行日志表 (可解释性核心)
-- -------------------------------------------
CREATE TABLE IF NOT EXISTS agent_execution_logs (
    id              BIGINT       AUTO_INCREMENT PRIMARY KEY,
    session_id      VARCHAR(36)  NOT NULL    COMMENT '会话ID',
    agent_name      VARCHAR(50)  NOT NULL    COMMENT 'Agent名称',
    step_index      INT          NOT NULL    COMMENT '执行步骤序号',
    thought         TEXT                     COMMENT 'Agent思考过程',
    action          VARCHAR(200)             COMMENT '执行的动作/工具',
    action_input    TEXT                     COMMENT '动作输入参数',
    observation     TEXT                     COMMENT '执行结果/观察',
    token_used      INT          DEFAULT 0   COMMENT 'Token消耗量',
    latency_ms      INT          DEFAULT 0   COMMENT '执行耗时(ms)',
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_session (session_id),
    INDEX idx_agent (agent_name),
    INDEX idx_created (created_at)
) ENGINE=InnoDB COMMENT='Agent执行日志表';

-- -------------------------------------------
-- 5. 风控策略表
-- -------------------------------------------
CREATE TABLE IF NOT EXISTS risk_strategies (
    strategy_id     VARCHAR(36)  PRIMARY KEY COMMENT '策略ID',
    name            VARCHAR(100) NOT NULL    COMMENT '策略名称',
    description     TEXT                     COMMENT '策略说明',
    trigger_condition JSON                   COMMENT '触发条件(JSON)',
    action_type     VARCHAR(50)  NOT NULL    COMMENT '动作: REJECT/REDUCE_LIMIT/MANUAL_REVIEW/MONITOR',
    action_params   JSON                     COMMENT '动作参数(JSON)',
    estimated_impact JSON                    COMMENT '预估影响(JSON)',
    compliance_status VARCHAR(30) DEFAULT 'PENDING_REVIEW' COMMENT '合规状态',
    status          ENUM('DRAFT','PENDING_REVIEW','ACTIVE','DISABLED')
                    DEFAULT 'DRAFT'          COMMENT '策略状态',
    created_by      VARCHAR(50)              COMMENT '创建者: agent/manual',
    approved_by     VARCHAR(50)              COMMENT '审批人',
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_status (status),
    INDEX idx_created (created_at)
) ENGINE=InnoDB COMMENT='风控策略表';

-- -------------------------------------------
-- 6. 分析报告表
-- -------------------------------------------
CREATE TABLE IF NOT EXISTS analysis_reports (
    report_id       VARCHAR(36)  PRIMARY KEY COMMENT '报告ID',
    session_id      VARCHAR(36)  NOT NULL    COMMENT '关联会话ID',
    title           VARCHAR(200) NOT NULL    COMMENT '报告标题',
    query_text      TEXT         NOT NULL    COMMENT '用户原始问题',
    summary         TEXT                     COMMENT '分析摘要',
    detail          JSON                     COMMENT '详细分析结果(JSON)',
    strategies      JSON                     COMMENT '关联策略建议(JSON)',
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_session (session_id),
    INDEX idx_created (created_at)
) ENGINE=InnoDB COMMENT='分析报告表';

-- -------------------------------------------
-- 7. 贷前申请人表
-- -------------------------------------------
CREATE TABLE IF NOT EXISTS applicants (
    applicant_id   VARCHAR(32) PRIMARY KEY,
    name           VARCHAR(50) NOT NULL COMMENT '申请人姓名',
    annual_income  DECIMAL(12,2) NOT NULL COMMENT '年收入',
    emp_title      VARCHAR(100) COMMENT '职业',
    emp_length     VARCHAR(20) COMMENT '工作年限',
    home_ownership VARCHAR(20) COMMENT '房产状况',
    province       VARCHAR(50) COMMENT '省份',
    city           VARCHAR(50) COMMENT '城市',
    dti            DECIMAL(5,2) COMMENT '负债收入比(%)',
    fico_score     INT COMMENT 'FICO信用评分',
    delinq_2yrs    INT DEFAULT 0 COMMENT '近2年逾期次数',
    inq_last_6mths INT DEFAULT 0 COMMENT '近6月信用查询次数',
    revol_util     DECIMAL(5,2) COMMENT '信用使用率(%)',
    open_acc       INT COMMENT '活跃信用账户数',
    total_acc      INT COMMENT '总信用账户数',
    pub_rec        INT DEFAULT 0 COMMENT '公共不良记录数',
    requested_amount DECIMAL(12,2) NOT NULL COMMENT '申请金额',
    requested_term   INT NOT NULL COMMENT '申请期限(月)',
    product_type     VARCHAR(20) NOT NULL COMMENT '申请产品类型',
    channel          VARCHAR(50) COMMENT '申请渠道',
    purpose          VARCHAR(50) COMMENT '借款用途',
    status           VARCHAR(20) DEFAULT 'PENDING' COMMENT '审批状态',
    approved_amount  DECIMAL(12,2) COMMENT '批准金额',
    approved_rate    DECIMAL(5,2) COMMENT '批准利率',
    risk_score       INT COMMENT '风险评分',
    risk_grade       VARCHAR(5) COMMENT '风险等级',
    decision_reason  TEXT COMMENT '审批理由',
    reviewed_at      DATETIME COMMENT '审批时间',
    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_status (status),
    INDEX idx_fico (fico_score),
    INDEX idx_created (created_at)
) ENGINE=InnoDB COMMENT='贷前申请人表';
