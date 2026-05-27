import { useEffect, useState } from "react";
import { AlertCircle, RefreshCw } from "lucide-react";
import {
  ComposedChart,
  Bar,
  Line,
  PieChart,
  Pie,
  Cell,
  Label,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import MetricsCards from "@/components/MetricsCards";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { getStats } from "@/services/api";
import type { StatsResponse } from "@/services/api";
import { cn } from "@/lib/utils";

// ── Color tokens ─────────────────────────────────────────────────

const STATUS_COLORS: Record<string, string> = {
  正常还款:   "#3b82f6",
  已结清:     "#10b981",
  逾期:       "#ef4444",
  核销:       "#f59e0b",
  展期:       "#8b5cf6",
  宽限期:     "#06b6d4",
};

const STATUS_LABELS: Record<string, string> = {
  current:          "正常还款",
  fully_paid:       "已结清",
  late:             "逾期",
  charged_off:      "核销",
  in_grace_period:  "展期",
  default:          "逾期",
};

const GRADE_BAR    = "#3b82f6";
const OVERDUE_LINE = "#ef4444";

// ── Shared helpers ────────────────────────────────────────────────

interface TooltipPayload {
  name: string;
  value: number;
  color: string;
}

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: TooltipPayload[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2 text-xs shadow-xl">
      {label && (
        <p className="mb-1.5 font-semibold text-foreground">{label}</p>
      )}
      {payload.map((entry) => (
        <div key={entry.name} className="flex items-center gap-2 leading-relaxed">
          <span
            className="h-2 w-2 shrink-0 rounded-full"
            style={{ background: entry.color }}
          />
          <span className="text-muted-foreground">{entry.name}:</span>
          <span className="ml-auto font-medium tabular-nums text-foreground">
            {typeof entry.value === "number"
              ? entry.value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })
              : entry.value}
            {entry.name.includes("逾期率") ? "%" : ""}
          </span>
        </div>
      ))}
    </div>
  );
}

// Recharts Label content for donut center
function DonutCenter({
  viewBox,
  total,
}: {
  viewBox?: { cx?: number; cy?: number };
  total: number;
}) {
  const cx = viewBox?.cx ?? 0;
  const cy = viewBox?.cy ?? 0;
  return (
    <g>
      <text
        x={cx}
        y={cy - 9}
        textAnchor="middle"
        dominantBaseline="central"
        style={{ fontSize: 20, fontWeight: 700, fill: "var(--foreground, #111)" }}
      >
        {total >= 10000
          ? `${(total / 10000).toFixed(1)}万`
          : total.toLocaleString("zh-CN")}
      </text>
      <text
        x={cx}
        y={cy + 13}
        textAnchor="middle"
        dominantBaseline="central"
        style={{ fontSize: 11, fill: "var(--muted-foreground, #71717a)" }}
      >
        总笔数
      </text>
    </g>
  );
}

// Section card wrapper
function SectionCard({
  title,
  subtitle,
  children,
  className,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("rounded-xl border border-border bg-card shadow-sm", className)}>
      <div className="border-b border-border px-5 py-3.5">
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        {subtitle && (
          <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>
        )}
      </div>
      <div className="p-5">{children}</div>
    </div>
  );
}

// ── Main Page ────────────────────────────────────────────────────

export default function DashboardPage() {
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = () => {
    setLoading(true);
    setError(null);
    getStats()
      .then((res) => setStats(res.data))
      .catch(() =>
        setError(
          "无法加载数据，请确认后端（端口 8000）及 MySQL / Redis 已启动。"
        )
      )
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchData();
  }, []);

  const statusData = stats?.status_distribution
    ? Object.entries(stats.status_distribution).map(([key, value]) => ({
        name: STATUS_LABELS[key] ?? key,
        value,
      }))
    : [];

  const totalLoans = statusData.reduce((s, d) => s + d.value, 0);
  const gradeData = stats?.grade_distribution ?? [];

  // Right Y-axis ceiling: max overdue rate + 25% headroom, rounded up to nearest integer
  const maxOverdue = gradeData.length
    ? Math.max(...gradeData.map((d) => d.overdue_rate_pct ?? 0))
    : 0;
  const overdueCeil = Math.max(Math.ceil(maxOverdue * 1.25), 1);

  return (
    <div className="mx-auto max-w-7xl space-y-5">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-foreground">
            数据概览
          </h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            核心风控指标 · 实时贷款组合分析
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={fetchData}
          disabled={loading}
          className="gap-1.5 text-xs"
        >
          <RefreshCw
            className={cn("h-3.5 w-3.5", loading && "animate-spin")}
          />
          刷新数据
        </Button>
      </div>

      {/* Error */}
      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* KPI Cards */}
      {loading ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 7 }).map((_, i) => (
            <Skeleton key={i} className="h-[84px] rounded-xl" />
          ))}
        </div>
      ) : (
        <MetricsCards summary={stats?.summary ?? null} loading={false} />
      )}

      {/* Charts row */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">

        {/* Donut – 2 cols */}
        <SectionCard
          title="贷款状态分布"
          subtitle="按还款状态拆分的贷款组合"
          className="lg:col-span-2"
        >
          {loading ? (
            <Skeleton className="h-[300px] rounded-lg" />
          ) : statusData.length === 0 ? (
            <p className="py-20 text-center text-sm text-muted-foreground">
              暂无分布数据
            </p>
          ) : (
            <div className="flex flex-col gap-4">
              <ResponsiveContainer width="100%" height={220}>
                <PieChart>
                  <Pie
                    data={statusData}
                    dataKey="value"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    outerRadius={92}
                    innerRadius={56}
                    strokeWidth={2}
                    stroke="hsl(var(--card, #fff))"
                    paddingAngle={2}
                    minAngle={5}
                    isAnimationActive
                  >
                    {statusData.map((entry, idx) => (
                      <Cell
                        key={idx}
                        fill={
                          STATUS_COLORS[entry.name] ??
                          `hsl(${idx * 55}, 60%, 55%)`
                        }
                      />
                    ))}
                    <Label
                      position="center"
                      content={(props) => (
                        <DonutCenter
                          viewBox={
                            props.viewBox as { cx?: number; cy?: number }
                          }
                          total={totalLoans}
                        />
                      )}
                    />
                  </Pie>
                  <Tooltip content={<ChartTooltip />} />
                </PieChart>
              </ResponsiveContainer>

              {/* Custom legend */}
              <div className="grid grid-cols-2 gap-x-4 gap-y-2">
                {statusData.map((entry, idx) => (
                  <div key={idx} className="flex items-center gap-1.5">
                    <span
                      className="h-2.5 w-2.5 shrink-0 rounded-sm"
                      style={{
                        background:
                          STATUS_COLORS[entry.name] ??
                          `hsl(${idx * 55}, 60%, 55%)`,
                      }}
                    />
                    <span className="truncate text-xs text-muted-foreground">
                      {entry.name}
                    </span>
                    <span className="ml-auto text-xs font-semibold tabular-nums text-foreground">
                      {totalLoans > 0
                        ? ((entry.value / totalLoans) * 100).toFixed(1)
                        : "0"}
                      %
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </SectionCard>

        {/* ComposedChart – 3 cols */}
        <SectionCard
          title="信用评级与逾期率"
          subtitle="各等级贷款数量（柱）及逾期率（折线）"
          className="lg:col-span-3"
        >
          {loading ? (
            <Skeleton className="h-[300px] rounded-lg" />
          ) : gradeData.length === 0 ? (
            <p className="py-20 text-center text-sm text-muted-foreground">
              暂无评级数据
            </p>
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <ComposedChart
                data={gradeData}
                margin={{ top: 8, right: 20, left: 0, bottom: 0 }}
              >
                <defs>
                  <linearGradient id="barGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={GRADE_BAR} stopOpacity={0.9} />
                    <stop offset="100%" stopColor={GRADE_BAR} stopOpacity={0.5} />
                  </linearGradient>
                </defs>

                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="hsl(var(--border, #e4e4e7))"
                  vertical={false}
                />
                <XAxis
                  dataKey="grade"
                  tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground, #71717a))" }}
                  axisLine={{ stroke: "hsl(var(--border, #e4e4e7))" }}
                  tickLine={false}
                />
                <YAxis
                  yAxisId="left"
                  tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground, #a1a1aa))" }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={(v: number) =>
                    v >= 1000 ? `${(v / 1000).toFixed(0)}k` : String(v)
                  }
                />
                <YAxis
                  yAxisId="right"
                  orientation="right"
                  tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground, #a1a1aa))" }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={(v: number) => `${v}%`}
                  domain={[0, overdueCeil]}
                />
                <Tooltip content={<ChartTooltip />} />
                <Legend
                  iconType="circle"
                  iconSize={8}
                  wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
                />
                <Bar
                  yAxisId="left"
                  dataKey="cnt"
                  name="贷款数量"
                  fill="url(#barGrad)"
                  radius={[5, 5, 0, 0]}
                  maxBarSize={48}
                  isAnimationActive
                />
                <Line
                  yAxisId="right"
                  dataKey="overdue_rate_pct"
                  name="逾期率(%)"
                  stroke={OVERDUE_LINE}
                  strokeWidth={2.5}
                  dot={{
                    fill: OVERDUE_LINE,
                    r: 4,
                    strokeWidth: 2,
                    stroke: "#fff",
                  }}
                  activeDot={{ r: 6 }}
                  isAnimationActive
                />
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </SectionCard>
      </div>

      {/* Table counts strip */}
      {!loading && stats?.table_counts && (
        <div className="rounded-xl border border-border bg-card px-5 py-4 shadow-sm">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            数据库表记录数
          </p>
          <div className="flex flex-wrap gap-x-8 gap-y-2">
            {Object.entries(stats.table_counts).map(([table, count]) => (
              <div key={table} className="flex items-baseline gap-1.5">
                <span className="font-mono text-xs text-muted-foreground">
                  {table}
                </span>
                <span className="text-sm font-bold tabular-nums text-foreground">
                  {Number(count).toLocaleString("zh-CN")}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
