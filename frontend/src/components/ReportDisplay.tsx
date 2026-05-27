import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { FileText, Download } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { StudioPanel } from "@/components/layout/StudioPanel";

interface Props {
  report: string;
  intent: string;
  latency: number;
  loading?: boolean;
}

// 匹配 export_to_csv 返回的下载链接格式：[点击下载 CSV](/api/v1/exports/{32位hex})
const EXPORT_LINK_RE = /\[点击下载 CSV\]\((\/api\/v1\/exports\/[a-f0-9]{32})\)/g;

function extractExportLinks(text: string): { url: string }[] {
  const links: { url: string }[] = [];
  let match;
  const re = new RegExp(EXPORT_LINK_RE.source, "g");
  while ((match = re.exec(text)) !== null) {
    links.push({ url: match[1] });
  }
  return links;
}

const intentLabels: Record<string, { label: string; variant: "default" | "warning" | "success" | "destructive" | "secondary" }> = {
  data_query: { label: "数据查询", variant: "default" },
  risk_analysis: { label: "风险分析", variant: "warning" },
  compliance: { label: "合规检查", variant: "success" },
  strategy: { label: "策略建议", variant: "destructive" },
  chitchat: { label: "对话", variant: "secondary" },
};

export default function ReportDisplay({ report, intent, latency, loading }: Props) {
  if (loading) {
    return (
      <StudioPanel className="mt-4">
        <div className="space-y-3">
          <Skeleton className="h-4 w-1/3" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      </StudioPanel>
    );
  }

  if (!report) {
    return (
      <StudioPanel className="mt-4">
        <div className="py-12 text-center text-sm text-muted-foreground">
          输入问题后，分析报告将显示在这里
        </div>
      </StudioPanel>
    );
  }

  const intentMeta = intentLabels[intent] || { label: intent || "分析", variant: "secondary" as const };
  const exportLinks = extractExportLinks(report);

  return (
    <StudioPanel
      className="mt-4"
      header={
        <span className="inline-flex items-center gap-2">
          <FileText className="h-4 w-4 text-primary" />
          分析报告
        </span>
      }
      extra={
        <div className="flex items-center gap-2">
          <Badge variant={intentMeta.variant}>{intentMeta.label}</Badge>
          <span className="tabular-nums text-xs text-muted-foreground">
            {(latency / 1000).toFixed(1)}s
          </span>
        </div>
      }
    >
      <article className="report-markdown">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{report}</ReactMarkdown>
      </article>

      {exportLinks.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-2 border-t pt-4">
          {exportLinks.map(({ url }, i) => (
            <a
              key={i}
              href={url}
              download
              className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground shadow-sm hover:bg-primary/90 transition-colors"
            >
              <Download className="h-3.5 w-3.5" />
              下载 CSV
            </a>
          ))}
        </div>
      )}
    </StudioPanel>
  );
}
