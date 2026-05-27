# Design System — Credit Risk Agent

由 [ui-ux-pro-max](.agents/skills/ui-ux-pro-max/) 生成，作为前端 UI 的**唯一视觉规范来源**。

## 文件结构

| 文件 | 用途 |
|------|------|
| `credit-risk-agent/MASTER.md` | 全局设计系统（颜色、字体、间距、组件、反模式） |
| `credit-risk-agent/pages/dashboard.md` | **数据概览页**覆盖规则（优先于 MASTER） |
| `credit-risk-agent/pages/<page>.md` | 其他页面覆盖（按需再生成） |

## Agent 使用方式

改 UI 前必须先读：

1. `design-system/credit-risk-agent/pages/<page-name>.md`（若存在）
2. 否则读 `design-system/credit-risk-agent/MASTER.md`

## 再生成命令（项目根目录）

```powershell
# 全局 MASTER
python .agents/skills/ui-ux-pro-max/scripts/search.py "fintech credit risk B2B dashboard data-dense professional" --design-system --persist -p "Credit Risk Agent"

# 单页覆盖（示例：分析页）
python .agents/skills/ui-ux-pro-max/scripts/search.py "AI chat analysis report agent timeline" --design-system --persist -p "Credit Risk Agent" --page "analysis"
```
