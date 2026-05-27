# 信贷风控 Agent 平台

Multi-Agent 协作的智能信贷风控分析系统，基于 LangGraph 实现多 Agent 编排，支持自然语言驱动的风控数据分析、风险归因、合规审查和策略建议。

## 架构

```
用户自然语言输入
      │
      ▼
┌──────────────┐
│ Router Agent │ 意图识别
└──────┬───────┘
       │
  ┌────┴────┬──────────┬──────────┐
  ▼         ▼          ▼          ▼
数据查询  风险归因    合规检查    策略建议
Agent     Agent      Agent      Agent
  │         │          │          │
  └────┬────┴──────────┴──────────┘
       ▼
  Report Agent → 汇总分析报告
```

## 技术栈

| 层 | 技术 |
|---|---|
| Agent 框架 | LangGraph + LangChain |
| LLM | OpenAI GPT-4o (可切换) |
| 后端 | FastAPI |
| 数据库 | MySQL 8.0 |
| 缓存 | Redis 7 |
| 容器 | Docker Compose |

## 快速开始

### 1. 环境准备

```bash
# 激活 conda 环境
conda activate llm2

# 安装依赖（大部分已在 llm2 中）
pip install faker
```

### 2. 启动基础设施

```bash
# 启动 MySQL + Redis
docker-compose up -d

# 等待 MySQL 就绪（约 10-20 秒）
docker-compose logs mysql
```

### 3. 准备数据

从 Kaggle 下载 Lending Club 数据集：
https://www.kaggle.com/datasets/wordsforthewise/lending-club

将 CSV 文件放到 `data/lending_club_raw.csv`，然后运行：

```bash
python scripts/data_pipeline.py
```

### 4. 配置 LLM

编辑 `.env` 文件，填入你的 API Key：

```
OPENAI_API_KEY=your_key_here
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o
```

### 5. 启动开发服务（推荐脚本）

```bash
# 启动后端 API + Celery Worker（会自动拉起 MySQL/Redis）
powershell -ExecutionPolicy Bypass -File scripts/dev_start.ps1
```

访问 http://localhost:8000/docs 查看 API 文档。

如需单独启动 Worker：

```bash
powershell -ExecutionPolicy Bypass -File scripts/worker_start.ps1
```

停止开发服务（后端/前端端口 + Celery Worker）：

```bash
powershell -ExecutionPolicy Bypass -File scripts/dev_stop.ps1
```

前端开发（可选，单独终端）：

```bash
powershell -ExecutionPolicy Bypass -File scripts/dev_start_frontend.ps1
```

### 5.1 三终端启动图（推荐）

```text
Terminal A (Backend API)      Terminal B (Celery Worker)        Terminal C (Frontend)
-------------------------     ---------------------------        ----------------------
cd agent-cursor               cd agent-cursor                   cd agent-cursor\frontend
conda activate llm2           conda activate llm2               npm run dev
python app.py                 celery -A src.infra.celery_app:celery_app worker -l info -P threads -c 4

职责：HTTP接口服务             职责：审批异步任务消费              职责：页面与交互
默认端口：8000                队列：Redis                        默认端口：3000/3001
```

排错建议：

- API 报错看 Terminal A
- 审批状态卡在 `PENDING/RUNNING` 看 Terminal B
- 页面请求失败看 Terminal C 和浏览器 Network

### 5.2 一键脚本启动对照表

| 场景 | 命令 | 说明 |
|---|---|---|
| 启动后端 + Worker（推荐） | `powershell -ExecutionPolicy Bypass -File scripts/dev_start.ps1` | 自动 `docker compose up -d`，拉起 Celery，再启动 API |
| 仅启动 Worker | `powershell -ExecutionPolicy Bypass -File scripts/worker_start.ps1` | 适合 API 已运行时单独重启任务消费者 |
| 启动前端 | `powershell -ExecutionPolicy Bypass -File scripts/dev_start_frontend.ps1` | 启动 Vite 开发服务 |
| 停止全部开发进程 | `powershell -ExecutionPolicy Bypass -File scripts/dev_stop.ps1` | 释放 8000/3000/3001/8010 并清理 Celery worker |

常见组合：

1. 全栈开发：先执行 `dev_start.ps1`，再开新终端执行 `dev_start_frontend.ps1`
2. 仅后端调试：执行 `dev_start.ps1` 即可
3. Worker 异常重启：先 `dev_stop.ps1`，再 `worker_start.ps1`

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/health` | GET | 健康检查 |
| `/api/v1/analyze` | POST | 执行风控分析 |
| `/api/v1/stats` | GET | 数据概览 |
| `/api/v1/sessions/{id}/logs` | GET | Agent 执行日志 |
| `/api/v1/applicants/generate` | POST | 生成待审批申请人 |
| `/api/v1/applicants` | GET | 申请人列表 |
| `/api/v1/applicants/{id}/approve` | POST | 提交异步审批任务 |
| `/api/v1/applicants/{id}/approve-status` | GET | 查询审批任务状态 |

### 示例请求

```bash
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{"query": "分析各信用评级的逾期率差异"}'
```

## 项目结构

```
credit-risk-agent/
├── app.py                      # FastAPI 入口
├── docker-compose.yml          # MySQL + Redis
├── requirements.txt            # Python 依赖
├── .env                        # 环境配置
├── sql/
│   └── init.sql                # 建表脚本
├── scripts/
│   ├── data_pipeline.py        # 数据清洗导入脚本
│   ├── dev_start.ps1           # 启动后端 + Worker
│   ├── worker_start.ps1        # 单独启动 Worker
│   ├── dev_start_frontend.ps1  # 启动前端
│   └── dev_stop.ps1            # 停止本地开发进程
├── src/
│   ├── config.py               # 配置管理
│   ├── database.py             # 数据库连接
│   ├── agents/
│   │   ├── data_query_agent.py # 数据查询 Agent
│   │   ├── risk_analysis_agent.py # 风险归因 Agent
│   │   ├── compliance_agent.py # 合规检查 Agent
│   │   ├── strategy_agent.py   # 策略建议 Agent
│   │   └── underwriting_agent.py # 授信审批 Agent
│   ├── infra/
│   │   ├── celery_app.py       # Celery 初始化
│   │   └── queue_service.py    # 任务队列服务
│   ├── tools/
│   │   ├── sql_tools.py        # SQL 执行工具
│   │   ├── analysis_tools.py   # 分析工具
│   │   ├── rag_tools.py        # 合规 RAG 工具
│   │   └── underwriting_tools.py # 授信审批工具
│   ├── graph/
│   │   └── workflow.py         # LangGraph 工作流编排
│   ├── tasks/
│   │   └── underwriting_tasks.py # Celery 审批任务
│   └── api/
│       └── routes.py           # API 路由
├── data/                       # 数据目录
└── docs/
    └── regulations/            # 监管文档
```

## 数据来源

- **Lending Club 贷款数据集** (226万+ 真实贷款记录, 分层抽样 5万条)
- 数据经过清洗、中文化映射，模拟花呗/借呗/网商贷业务场景
