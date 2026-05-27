import {
  AlertTriangle,
  Banknote,
  DollarSign,
  FileText,
  Percent,
  TrendingUp,
  Users,
} from "lucide-react";
import type { MetricsSummary } from "@/services/api";
import { toNum } from "@/lib/utils";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";

interface Props {
  summary: MetricsSummary | null;
  loading: boolean;
}

function formatMoney(v: number): string {
  if (v >= 1e8) return (v / 1e8).toFixed(2) + " 亿";
  if (v >= 1e4) return (v / 1e4).toFixed(0) + " 万";
  return v.toLocaleString("zh-CN");
}

function formatCount(v: number): string {
  if (v >= 1e4) return v.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
  return String(v);
}

interface TileConfig {
  label: string;
  display: string;
  suffix?: string;
  icon: React.ComponentType<{ className?: string }>;
  iconBg: string;
  iconColor: string;
  valueColor?: string;
}

function MetricTile({
  label,
  display,
  suffix,
  icon: Icon,
  iconBg,
  iconColor,
  valueColor,
  loading,
}: TileConfig & { loading: boolean }) {
  if (loading) {
    return (
      <div className="rounded-xl border border-border bg-card p-4 shadow-sm">
        <div className="flex items-start justify-between">
          <div className="flex-1 space-y-2.5 pt-0.5">
            <Skeleton className="h-3 w-14 rounded" />
            <Skeleton className="h-7 w-24 rounded" />
          </div>
          <Skeleton className="h-9 w-9 rounded-lg" />
        </div>
      </div>
    );
  }

  return (
    <div className="group rounded-xl border border-border bg-card p-4 shadow-sm transition-all duration-200 hover:shadow-md hover:border-border/60">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            {label}
          </p>
          <p
            className={cn(
              "mt-1.5 text-2xl font-bold tabular-nums leading-none tracking-tight",
              valueColor ?? "text-foreground"
            )}
          >
            {display}
            {suffix && (
              <span className="ml-0.5 text-sm font-medium text-muted-foreground">
                {suffix}
              </span>
            )}
          </p>
        </div>
        <div
          className={cn(
            "shrink-0 rounded-lg p-2 transition-transform duration-200 group-hover:scale-110",
            iconBg
          )}
        >
          <Icon className={cn("h-5 w-5", iconColor)} />
        </div>
      </div>
    </div>
  );
}

export default function MetricsCards({ summary, loading }: Props) {
  const overdue = toNum(summary?.overdue_rate_pct);
  const bad = toNum(summary?.bad_rate_pct);
  const totalLoan = toNum(summary?.total_loan_amount);
  const outstanding = toNum(summary?.total_outstanding);
  const rate = toNum(summary?.avg_interest_rate);

  const tiles: TileConfig[] = [
    {
      label: "逾期率",
      display: overdue.toFixed(2),
      suffix: "%",
      icon: AlertTriangle,
      iconBg: overdue > 10 ? "bg-red-50" : "bg-emerald-50",
      iconColor: overdue > 10 ? "text-red-500" : "text-emerald-500",
      valueColor: overdue > 10 ? "text-red-600" : "text-emerald-600",
    },
    {
      label: "不良率",
      display: bad.toFixed(2),
      suffix: "%",
      icon: TrendingUp,
      iconBg: bad > 5 ? "bg-amber-50" : "bg-emerald-50",
      iconColor: bad > 5 ? "text-amber-500" : "text-emerald-500",
      valueColor: bad > 5 ? "text-amber-600" : "text-emerald-600",
    },
    {
      label: "总放款额",
      display: formatMoney(totalLoan),
      icon: DollarSign,
      iconBg: "bg-blue-50",
      iconColor: "text-blue-600",
    },
    {
      label: "用户数",
      display: formatCount(toNum(summary?.total_users)),
      icon: Users,
      iconBg: "bg-violet-50",
      iconColor: "text-violet-600",
    },
    {
      label: "在贷余额",
      display: formatMoney(outstanding),
      icon: Banknote,
      iconBg: "bg-sky-50",
      iconColor: "text-sky-600",
    },
    {
      label: "平均利率",
      display: rate.toFixed(2),
      suffix: "%",
      icon: Percent,
      iconBg: "bg-emerald-50",
      iconColor: "text-emerald-600",
    },
    {
      label: "贷款笔数",
      display: formatCount(toNum(summary?.total_loans)),
      icon: FileText,
      iconBg: "bg-slate-100",
      iconColor: "text-slate-600",
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
      {tiles.map((tile) => (
        <MetricTile key={tile.label} {...tile} loading={loading} />
      ))}
    </div>
  );
}
