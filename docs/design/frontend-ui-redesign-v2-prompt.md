# 信贷风控 Agent 前端 UI 大改版 — 设计提示词 v2

> **状态：** 待评审（仅提示词，尚未实施）  
> **生成依据：** `ui-ux-pro-max` skill + 现有 `design-system/` + 当前 `frontend/` 代码盘点  
> **参考产品：** [Langfuse](https://langfuse.com)（Observability / Traces）、[Supabase Studio](https://supabase.com/dashboard)（开发者工具控制台）

---

## 0. 为什么需要 v2（对上一版的诊断）

上一版改版**代码已动，但视觉气质未变**，根因如下：

| 问题 | 表现 |
|------|------|
| **Ant Design 默认形态过重** | `Card` / `Table` / `Input.Search` 的圆角、边框、内边距仍是「企业后台」语言 |
| **信息架构未变** | 仍是「侧栏 + 页头 + 卡片堆叠」，缺少 Langfuse 的 **列表-详情分栏**、Supabase 的 **工具栏 + 数据区** 节奏 |
| **色彩系统摇摆** | MASTER 蓝 + 改版 zinc 灰混用，缺少单一、克制的 **中性色 + 一个强调色** 体系 |
| **页面 override 文档空洞** | `pages/*.md` 仍是通用模板句，未指导具体布局 |
| **改动幅度不够** | 换字体/浅侧栏属于「换皮」，不是「换产品结构」 |

**v2 目标：** 一眼看出是 **开发者向 Observability / Data Console**，而不是 Ant Design Pro 后台。

---

## 1. 产品定位与设计原则

### 1.1 产品类型（skill 输入）

```
fintech credit risk B2B observability dashboard
langfuse supabase studio style
data-dense professional minimal
react ant design keep library
```

### 1.2 风格选型（ui-ux-pro-max 推荐 + 人工收敛）

| 维度 | 选型 | 说明 |
|------|------|------|
| **主风格** | Data-Dense Dashboard + Swiss Minimalism | 高密度数据、网格对齐、装饰极少 |
| **参考气质** | Langfuse Traces / Supabase Table Editor | 工具感、可扫描、mono 数字 |
| **模式** | Light only（v2 不做暗色，避免范围膨胀） | 背景 `#FAFAFA`，表面 `#FFFFFF` |
| **禁止** | Glassmorphism 大面积、AI 紫粉渐变、拟物阴影、emoji 图标 | 见 MASTER anti-patterns |

### 1.3 五条设计原则

1. **Content over chrome** — 边框/阴影只用于分区，不用于装饰  
2. **Scan first** — KPI、表格、日志优先可读；标题字号克制（20px 顶栏即可）  
3. **One primary action per view** — 分析页只有「开始分析」是主 CTA（琥珀色，见硬约束）  
4. **Stable layout** — 加载用 Skeleton，禁止布局跳动（CLS）  
5. **Numbers are sacred** — 指标/ID/耗时一律 `tabular-nums` + mono 字体

---

## 2. 硬约束（实施时不可违反）

```text
【必须保留 — 按钮】
- 不得修改 frontend/src/theme.ts 中 components.Button 的配置
- 不得修改 Input.Search 的 enterButton / 文案「开始分析」/ 琥珀色 #D97706
- 策略页 Table 内「启用」「禁用」「刷新」等 Button 保持现有 theme 表现

【技术栈】
- React + Vite + Ant Design（保留），可改 layout、CSS、组件结构，不换 UI 库

【数据安全】
- API 数值字段可能是 string，所有展示层必须 Number() 防御性转换
```

---

## 3. 新设计系统 Token（建议写入 MASTER v2）

> 与 ui-ux-pro-max 脚本输出对齐，并 **保留琥珀 CTA**（仅用于 Button primary，不作为全局 accent token）。

### 3.1 色彩

| Role | Hex | 用途 |
|------|-----|------|
| Canvas | `#FAFAFA` | 页面底色（非纯白） |
| Surface | `#FFFFFF` | 面板、表格底 |
| Border | `#E4E4E7` | 分割线（zinc-200） |
| Border subtle | `#F4F4F5` | 行分隔 |
| Text primary | `#18181B` | 主文案（zinc-900） |
| Text secondary | `#71717A` | 说明、表头（zinc-500） |
| Text tertiary | `#A1A1AA` | 占位、meta（zinc-400） |
| Brand / Link | `#2563EB` | 链接、选中态、图表主色（blue-600） |
| Brand muted | `#EFF6FF` | 选中行背景 |
| Success | `#059669` | 正常指标 |
| Warning | `#D97706` | **仅 CTA 按钮**（theme Button） |
| Danger | `#DC2626` | 逾期/禁用 |
| Sidebar | `#FAFAFA` | 与 canvas 同系，右边框分隔 |

**不再使用：** 深蓝 `#1E3A8A` 侧栏、浅蓝 `#DBEAFE` 大面积边框（典型 Ant 金融后台感）。

### 3.2 字体

| 用途 | 字体 |
|------|------|
| UI 文案 | **Inter** 400/500/600 |
| 数字 / ID / 耗时 | **Geist Mono** 或 **Fira Code** 400/500 |

> skill 推荐 Fira Code + Fira Sans；若与 MASTER「Inter」冲突，**UI 用 Inter，数据用 Fira Code**。

### 3.3 间距与圆角（8px 网格）

| Token | 值 |
|-------|-----|
| radius-sm | 4px |
| radius-md | 6px |
| radius-lg | 8px（面板，不超过 8px，更「工具」） |
| space-1 ~ 6 | 4 / 8 / 12 / 16 / 24 / 32 px |

### 3.4 阴影

**默认无阴影。** 仅下拉、Modal 使用：`0 4px 16px rgba(0,0,0,0.08)`。

---

## 4. 全局 Shell（大改重点）

### 4.1 目标线框

```text
┌────────────┬──────────────────────────────────────────────────────────┐
│  SIDEBAR   │  TOPBAR (52px)                                           │
│  240px     │  信贷风控 / 智能分析          [环境标签] [可选: 健康状态]   │
│            ├──────────────────────────────────────────────────────────┤
│  [Logo]    │                                                          │
│            │  PAGE TOOLBAR (可选, 40px)  筛选 | 刷新 | 次要操作         │
│  导航      │                                                          │
│  · 分析    │  MAIN (padding 24px, max-width none 或 1440px)            │
│  · 概览    │                                                          │
│  · 策略    │  ┌─ 内容：尽量不用 Ant Card 外壳 ─────────────────────┐  │
│            │  │  直接 surface + border                             │  │
│            │  └────────────────────────────────────────────────────┘  │
│  [折叠]    │                                                          │
└────────────┴──────────────────────────────────────────────────────────┘
```

### 4.2 与 Supabase / Langfuse 的对照

| 元素 | Supabase Studio | Langfuse | 本项目 v2 |
|------|-----------------|----------|-----------|
| 侧栏 | 浅灰、细边框、小字号 | 窄、图标+文字 | 浅灰侧栏 + 左侧 3px 激活条 |
| 顶栏 | 项目面包屑 | Trace 路径 | `产品名 / 页面名` + 右侧 meta |
| 主区 | 全宽表格 | 左列表右详情 | 分析页采用 **分栏**（见 §5） |
| 表格 | 紧凑行高 40px | 高密度 | Table `size="small"` + 自定义 header |
| 卡片 | 极少 | 极少 | 用 `.studio-panel` 代替 `Card` |

### 4.3 组件策略（Ant Design 用法）

| 继续用 Ant | 包一层 / CSS 覆盖 | 自建 DOM + CSS |
|------------|-------------------|----------------|
| `Input.Search`（CTA 不改） | `Table`, `Select`, `Tag`, `Modal` | `StudioPanel`, `PageToolbar`, `MetricTile` |
| `Button`（theme 不改） | `Timeline` → 改为紧凑 steps 列表 | 侧栏、顶栏、面包屑 |
| `message`, `Alert`, `Skeleton` | `Statistic` → 不用，改 MetricTile | 分析页「执行链路」 |

---

## 5. 分页面规格

### 5.1 智能分析 `/`（Langfuse Traces 化 — 最大改动）

**布局：** 非对称双栏（≥1200px）；移动端单栏堆叠。

```text
┌─────────────────────────────────────────────┬─────────────────────┐
│  TOOLBAR: [状态 pill]  会话 id (mono)       │  历史 (固定宽 280px) │
├─────────────────────────────────────────────┤  搜索框 filter     │
│  COMMAND BAR (全宽)                          │  ─────────────────  │
│  [ 大输入框 ........................ ] [开始分析]│  trace 列表样式   │
│  示例 chips（pill，非 Ant Tag 默认色）        │  · 标题             │
├─────────────────────────────────────────────┤  · 时间 mono       │
│  REPORT PANEL                                │  · intent badge    │
│  header: 分析报告 | intent | 1.2s            │                     │
│  body: markdown 宽松行高 1.7                 │                     │
├─────────────────────────────────────────────┤                     │
│  RUN LOG (原 AgentTimeline)                  │                     │
│  紧凑表格: Agent | Action | ms | [展开]      │                     │
└─────────────────────────────────────────────┴─────────────────────┘
```

**交互：**

- 加载：Report 区 Skeleton，禁止整页白屏  
- 空态：Langfuse 式文案 + 示例 chip，无 `Empty.PRESENTED_IMAGE_SIMPLE` 默认插图  
- 历史点击 = 重新 submit（保持现有逻辑）

**去掉：** 页面内重复 `PageHeader` 大标题（顶栏面包屑已表达）

---

### 5.2 数据概览 `/dashboard`（Supabase Reports + Executive KPI）

```text
┌──────────────────────────────────────────────────────────────────┐
│  KPI ROW (6~7 个，横向滚动或 4+3 网格)                            │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐                       │
│  │ 逾期率 │ │ 不良率 │ │ 总放款 │ │ 用户数 │  ...                  │
│  │ 12.34% │ │  3.21% │ │  1.2M  │ │  8.5k  │  数字 28px bold mono  │
│  └────────┘ └────────┘ └────────┘ └────────┘                       │
├──────────────────────────────┬───────────────────────────────────┤
│  贷款状态 (donut)             │  评级 × 逾期 (grouped bar)          │
│  图例右侧或底部               │  网格线 #F4F4F5 only                │
└──────────────────────────────┴───────────────────────────────────┘
```

**图表（skill chart 域）：**

- KPI：Bullet 思维 — 数字 + 状态色，不用 Ant `Statistic` 默认样式  
- 状态分布：Donut `innerRadius 55%`，最多 7 色，来自 token 序列  
- 评级柱状：双 Y 轴，柱宽细、圆角 2px  
- **所有 API 数值 `toNum()` 转换**

---

### 5.3 策略管理 `/strategies`（Supabase Table Editor）

```text
┌──────────────────────────────────────────────────────────────────┐
│  TOOLBAR:  [状态 Select]  [刷新]                    共 N 条策略    │
├──────────────────────────────────────────────────────────────────┤
│  TABLE (full bleed in panel, row height 44px)                    │
│  表头: 11px uppercase zinc-500                                   │
│  列: 名称 | 描述 | 状态 Tag | 来源 | 时间 mono | 操作(按钮不改)  │
└──────────────────────────────────────────────────────────────────┘
```

**表格：**

- 外层 `.studio-panel`，不用 `Card` title  
- 行 hover `#FAFAFA`  
- 描述列 `ellipsis` + `title` tooltip  

---

## 6. CSS 架构（实施时）

```text
frontend/src/
  styles/
    tokens.css      # CSS variables，与 design-tokens.ts 同步
    shell.css       # sidebar, topbar, layout
    panels.css      # .studio-panel, .studio-toolbar
    analysis.css
    dashboard.css
  index.css         # 只 @import 上述 + ant overrides
```

**Ant 全局覆盖（index.css 或 `ant-overrides.css`）：**

- `Card`：实施阶段 **分析/概览/策略主内容禁止用 Card**，仅 Modal 等保留  
- `Table`：header 高 36px，cell padding `10px 16px`  
- `Tag`：height 22px，font 11px  
- `Input`：height 40px，border `#E4E4E7`

---

## 7. 实施顺序与验收标准

### 7.1 顺序

1. 更新 `design-system/credit-risk-agent/MASTER.md` + 重写 `pages/*.md`（本提示词 §3、§5）  
2. `design-tokens.ts` + `styles/*.css` + 精简 `index.css`  
3. `App.tsx` shell（TopBar + Sidebar v2）  
4. 分析页（分栏 + RunLog 表格化）  
5. 概览页（MetricTile + charts）  
6. 策略页（toolbar + table panel）  
7. 每步 `npm run build`；最后手工点三页 + 概览 API 数据

### 7.2 验收清单（ui-ux-pro-max Pre-Delivery）

- [ ] 侧栏/顶栏一眼不同于改版前（浅灰工具风，非深蓝 Ant Sider）  
- [ ] 主内容区无「大 Card 套小 Card」  
- [ ] 分析页有明确左右分栏（桌面）  
- [ ] KPI 数字 mono + 大字号  
- [ ] 开始分析按钮仍为琥珀色 #D97706  
- [ ] 策略页启用/禁用/刷新按钮样式未变  
- [ ] 数据概览在 string 数值下不崩溃  
- [ ] 375 / 1024 / 1440 三档布局可用  
- [ ] `prefers-reduced-motion` 保留  

---

## 8. 给实施 Agent 的一键提示词（复制即用）

```text
请按 docs/design/frontend-ui-redesign-v2-prompt.md 实施信贷风控 Agent 前端 UI 大改版 v2。

实施前必读：
1. design-system/credit-risk-agent/pages/<page>.md（实施时先用本提示词 §5 重写这三个文件）
2. design-system/credit-risk-agent/MASTER.md（按 §3 更新 token）
3. docs/design/frontend-ui-redesign-v2-prompt.md（全文）

硬约束：
- 不改 theme.ts components.Button
- 不改 Input.Search enterButton「开始分析」琥珀色 #D97706
- 策略页启用/禁用/刷新 Button 保持现有 theme
- 保留 React + Vite + Ant Design

风格目标：Langfuse / Supabase Studio 开发者控制台，克制、高密度、非 Ant Design 后台感。
主内容禁用 Ant Card 外壳，改用 .studio-panel。
分析页桌面端：左主栏（输入+报告+链路）+ 右历史列表（280px）。
所有指标数值 toNum() 防御。

顺序：design-system → tokens/css → App shell → Analysis → Dashboard → Strategy，每步 npm run build。
```

---

## 9. 可选：重新生成 design-system 命令

评审通过后可执行（覆盖 MASTER + 三页 override）：

```powershell
cd "l:\pycharm_LLM\课题二\agent-cursor"

python .agents/skills/ui-ux-pro-max/scripts/search.py `
  "fintech credit risk observability dashboard langfuse supabase data-dense minimal" `
  --design-system --persist -p "Credit Risk Agent"

python .agents/skills/ui-ux-pro-max/scripts/search.py `
  "AI analysis trace timeline command bar" `
  --design-system --persist -p "Credit Risk Agent" --page "analysis"

python .agents/skills/ui-ux-pro-max/scripts/search.py `
  "executive KPI metrics charts bento" `
  --design-system --persist -p "Credit Risk Agent" --page "dashboard"

python .agents/skills/ui-ux-pro-max/scripts/search.py `
  "data table editor CRUD status filter" `
  --design-system --persist -p "Credit Risk Agent" --page "strategies"
```

> 生成后需人工把 **琥珀 CTA #D97706** 写回 MASTER 的 Button/Accent 说明，避免被脚本覆盖为蓝色 CTA。

---

## 10. 请你评审的决策点

实施前请确认：

1. **侧栏**：浅灰（Supabase）vs 深色（Langfuse 部分页面）— v2 推荐 **浅灰**  
2. **分析页历史**：右侧固定栏 vs 抽屉 — v2 推荐 **右侧固定栏（桌面）**  
3. **字体**：Inter + Fira Code — 是否同意？  
4. **品牌主色**：蓝色 `#2563EB` 用于链接/图表，琥珀仅 CTA — 是否同意？  

你确认后回复「按 v2 提示词实施」或指出要改的点，再开始改代码。
