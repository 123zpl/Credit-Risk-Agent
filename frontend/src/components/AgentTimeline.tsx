import { Bot, CheckCircle2, ChevronDown, ChevronRight, Clock } from "lucide-react";
import { useState } from "react";
import type { ExecutionLog } from "@/services/api";
import { Badge } from "@/components/ui/badge";
import { StudioPanel } from "@/components/layout/StudioPanel";

interface Props {
  logs: ExecutionLog[];
}

const agentVariant: Record<string, "default" | "secondary" | "warning" | "success" | "destructive"> = {
  router: "secondary",
  chat: "secondary",
  data_query_agent: "default",
  risk_analysis_agent: "warning",
  compliance_agent: "success",
  strategy_agent: "destructive",
  report_generator: "default",
};

const agentLabels: Record<string, string> = {
  router: "路由器",
  chat: "对话 Agent",
  data_query_agent: "数据查询",
  risk_analysis_agent: "风险归因",
  compliance_agent: "合规检查",
  strategy_agent: "策略建议",
  report_generator: "报告生成",
};

function LogRow({ log, isLast }: { log: ExecutionLog; isLast: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-b border-border last:border-0">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full cursor-pointer items-center gap-3 px-4 py-3 text-left hover:bg-muted/50"
      >
        {isLast ? (
          <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" />
        ) : (
          <Clock className="h-4 w-4 shrink-0 text-muted-foreground" />
        )}
        <Badge variant={agentVariant[log.agent] || "secondary"}>
          {agentLabels[log.agent] || log.agent}
        </Badge>
        <span className="flex-1 truncate text-sm text-muted-foreground">{log.action}</span>
        <span className="tabular-nums text-xs text-muted-foreground">{log.latency_ms}ms</span>
        {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
      </button>
      {open && (
        <pre className="mx-4 mb-3 max-h-48 overflow-auto rounded-md border border-border bg-muted p-3 font-mono text-xs leading-relaxed">
          {log.result}
        </pre>
      )}
    </div>
  );
}

export default function AgentTimeline({ logs }: Props) {
  if (!logs?.length) return null;

  return (
    <StudioPanel
      className="mt-4"
      header={
        <span className="inline-flex items-center gap-2">
          <Bot className="h-4 w-4 text-primary" />
          Agent 执行链路
        </span>
      }
      extra={<span className="text-xs font-normal text-muted-foreground">{logs.length} 步</span>}
      bodyClassName="p-0"
    >
      {logs.map((log, idx) => (
        <LogRow key={idx} log={log} isLast={idx === logs.length - 1} />
      ))}
    </StudioPanel>
  );
}
