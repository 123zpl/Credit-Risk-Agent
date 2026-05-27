# 信贷风控 Agent 平台

基于 **LangGraph** 的多 Agent 信贷风控系统：支持自然语言驱动的数据分析、风险归因、合规审查、策略建议，以及 **C 端贷款申请 → Celery 异步贷前审批** 完整链路。

<p align="center">
  <img src="docs/images/数据概览.png" alt="数据概览看板" width="920"/>
</p>
<p align="center"><sub>数据概览：贷款规模、逾期率、产品分布与风险指标一览</sub></p>

---

## 核心能力

| 模块 | 说明 |
|------|------|
| **智能分析** | 用户自然语言提问 → Supervisor 规划 → 数据/风险/合规/策略 Worker 协作 → 统一汇总回复 |
| **贷前授信** | 运营端批量/单笔审批；C 端 `/apply` 提交后 Celery 跑独立审批工作流 |
| **数据看板** | 贷款指标概览、策略列表与导出 |
| **安全护栏** | SQL 表白名单 + 只读校验 + AST 守卫；审批规则引擎 + 合规硬检查 |

---

## 界面预览

### 数据看板（`/dashboard`）

![数据概览](docs/images/数据概览.png)

### 贷前授信（`/underwriting`）

运营端查看待审批队列、已处理记录，并打开 Agent 生成的审批报告。

| 待审批 | 已处理 |
|:---:|:---:|
| ![贷前授信-待审批](docs/images/贷前授信审批.png) | ![贷前授信-已处理](docs/images/贷前授信审批-已处理.png) |

**审批报告详情**（含决策、风险评分与政策依据摘要）：

![贷前授信-审批报告](docs/images/贷前授信审批-报告.png)

> 贷款申请入口见 `/apply`：提交后由 Celery 异步执行贷前审批工作流，列表自动刷新至「已处理」。

---

## 架构

系统包含 **两条 LangGraph 工作流**，共用 MySQL / Redis，审批链路额外依赖 Milvus RAG。

### 1. 主分析工作流（同步 HTTP）

```
用户 query + 会话历史
        │
        ▼
  entry_router（规则，零 LLM）
   ├─ 含申请人 ID + 审批意图 → underwriting 节点（内嵌子图，对话入口）
   ├─ 无历史 + 纯查数 → data_query 直路由（跳过 Supervisor 规划）
   └─ 其余 → Supervisor 主 Agent
              ├─ 问候/简单问答 → direct_reply
              └─ 复杂分析 → create_analysis_plan → plan_router 调度 Workers
                        data_query → risk_analysis → strategy / compliance
                        → supervisor_respond → 最终报告
```

### 2. 贷前审批工作流（Celery 异步）

由 `POST /applicants/submit` 或 `POST /applicants/{id}/approve` 入队，与主分析图的 Supervisor `plan` **解耦**。

```
fetch_applicant
      │
      ├──────────────┬──────────────┐
      ▼              ▼              ▼
 match_similar   retrieve_policies  risk_scoring   （并行 fan-out）
      │              │              │
      └──────────────┴──────────────┘
                     ▼
         underwriting_decision（规则兜底 + LLM 报告）
                     ▼
           compliance_check（利率/额度/收入倍数/用途）
                     ▼
              写入 applicants 终态
```

前端通过 **HTTP 轮询** `approve-status` / 列表刷新感知任务完成（非 SSE/WebSocket）。

---

## 技术栈

| 层 | 技术 |
|----|------|
| Agent 编排 | LangGraph + LangChain |
| LLM / Embedding | 通义千问 **Qwen**（[DashScope](https://help.aliyun.com/zh/model-studio/) OpenAI 兼容接口）；环境变量名沿用 `OPENAI_*`（`langchain-openai` 约定） |
| 后端 | FastAPI + Uvicorn（默认 **8001**） |
| 任务队列 | Celery + Redis |
| 数据库 | MySQL 8.0 |
| 向量检索 | Milvus（法规库 + 授信政策库） |
| 前端 | React 19 + Vite + Tailwind（默认 **3000**） |
| 基础设施 | Docker Compose（MySQL + Redis） |

---

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- Docker（MySQL、Redis）
- Milvus（RAG；需自行部署或使用已有实例）

### 1. 克隆与依赖

```bash
git clone https://github.com/123zpl/Credit-Risk-Agent.git
cd Credit-Risk-Agent

python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate

pip install -r requirements.txt

cd frontend && npm install && cd ..
```

### 2. 环境变量

复制并编辑 `.env`（勿提交到 Git）。变量名以 `src/config.py` 为准，常用项示例：

```env
# LLM（DashScope OpenAI 兼容模式）
OPENAI_API_KEY=your_dashscope_api_key
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_MODEL=qwen-plus

# Embedding
EMBEDDING_API_KEY=your_dashscope_api_key
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=text-embedding-v3

# MySQL / Redis（默认值见 docker-compose.yml）
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=credit_user
MYSQL_PASSWORD=change_me
MYSQL_DATABASE=credit_risk_db

REDIS_HOST=localhost
REDIS_PORT=6379

# Milvus
MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_COLLECTION=regulation_docs
CREDIT_POLICY_COLLECTION=credit_policies
```

### 3. 启动基础设施

```bash
docker compose up -d
```

初始化 RAG 索引（需 Milvus 与 Embedding 配置正确）：

```bash
python scripts/init_rag.py
```

### 4. 启动应用

**方式 A — 三个进程（跨平台通用）**

| 进程 | 工作目录 | 命令 |
|------|----------|------|
| API | 仓库根目录 | `python app.py` |
| Celery | 仓库根目录 | `celery -A src.infra.celery_app:celery_app worker -l info -P threads -c 4` |
| 前端 | `frontend/` | `npm run dev` |

**方式 B — Windows PowerShell 脚本**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev_start.ps1
powershell -ExecutionPolicy Bypass -File scripts/dev_start_frontend.ps1
# 停止：scripts/dev_stop.ps1
```

### 5. 访问

| 地址 | 说明 |
|------|------|
| http://localhost:3000 | Web 前端 |
| http://localhost:8001/docs | API 文档 |
| http://localhost:8001/api/v1/health | 健康检查 |

### 6. 演示数据（可选）

仓库默认**不包含**大体积 `data/`。可选步骤：

1. 下载 [Lending Club 数据集](https://www.kaggle.com/datasets/wordsforthewise/lending-club)
2. 放置为 `data/lending_club_raw.csv`
3. 运行 `python scripts/data_pipeline.py`

也可通过 `POST /api/v1/applicants/generate` 生成模拟申请人体验审批流程。

---

## 前端页面

| 路径 | 功能 | 截图 |
|------|------|------|
| `/` | 多轮风控分析对话 | — |
| `/dashboard` | 数据概览 | [数据概览](docs/images/数据概览.png) |
| `/strategies` | 策略列表 | — |
| `/underwriting` | 贷前授信（待审批 / 已处理 / 报告） | [待审批](docs/images/贷前授信审批.png) · [已处理](docs/images/贷前授信审批-已处理.png) · [报告](docs/images/贷前授信审批-报告.png) |
| `/apply` | C 端贷款申请 → 自动触发审批 | — |

---

## 主要 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/health` | 健康检查 |
| POST | `/api/v1/analyze` | 风控分析 |
| GET | `/api/v1/stats` | 数据概览 |
| GET | `/api/v1/sessions/{id}/logs` | 执行日志 |
| GET | `/api/v1/sessions/{id}/messages` | 会话消息 |
| GET | `/api/v1/reports` | 报告列表 |
| GET | `/api/v1/strategies` | 策略列表 |
| GET | `/api/v1/applicants` | 申请人列表 |
| GET | `/api/v1/applicants/form-options` | 申请表单选项 |
| POST | `/api/v1/applicants/submit` | 提交申请（可自动审批） |
| POST | `/api/v1/applicants/generate` | 生成模拟申请人 |
| POST | `/api/v1/applicants/{id}/approve` | 异步审批 |
| GET | `/api/v1/applicants/{id}/approve-status` | 任务状态 |
| POST | `/api/v1/applicants/batch-approve` | 批量审批 |

### 示例

```bash
curl -X POST http://localhost:8001/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{"query": "分析各信用评级的逾期率差异"}'
```

---

## 项目结构

```
Credit-Risk-Agent/
├── app.py
├── docker-compose.yml
├── requirements.txt
├── frontend/
├── sql/init.sql
├── scripts/
├── docs/images/              # README 截图
├── docs/policies/ docs/regulations/
└── src/
    ├── agents/
    ├── api/
    ├── graph/          # workflow, supervisor, plan_router, entry_intent
    ├── infra/          # celery, RAG
    ├── services/
    ├── tasks/
    └── underwriting/
```

---

## 设计要点

- **Supervisor Plan-then-Execute**：主 Agent 规划，Worker 无状态执行，`supervisor_respond` 统一对客回复。
- **审批与主分析解耦**：贷前固定 DAG + Celery，不进入 Supervisor `execution_plan`。
- **工具安全**：SQL 经白名单与 `sql_ast_guard` 校验后执行。
- **会话记忆**：默认本地 JSONL（`.agent_memory/`，已在 `.gitignore` 排除）。

---

## 安全提示

- 勿将 `.env`、API Key、会话记忆目录提交到公开仓库。
- 生产环境请修改默认数据库口令，并轮换已暴露的密钥。
- LLM 与自动化审批输出仅供演示，不构成真实授信意见。

---

## 许可证

演示与学习用途。业务数据请遵循 Kaggle Lending Club 数据集许可。
