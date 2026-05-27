import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  BadgeCheck,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  FileText,
  Loader2,
  RefreshCw,
  Settings2,
  Sparkles,
  Trash2,
  TrendingUp,
  Users,
  X,
  XCircle,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import PageHeader from "@/components/PageHeader";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  approveApplicant,
  batchApprove,
  deleteApplicant,
  deleteApplicantsBatch,
  generateApplicants,
  getApproveStatus,
  listApplicants,
  resetApplicant,
} from "@/services/api";
import type { Applicant, ApproveStatusResponse, ScoreBreakdown } from "@/services/api";
import { cn } from "@/lib/utils";

// ── Types ───────────────────────────────────────────────────────────────────

interface BatchTask { applicant_id: string; task_id: string; }
interface BatchProgress { total: number; done: number; failed: number; }

// ── Status helpers ──────────────────────────────────────────────────────────

const STATUS_LABEL: Record<string, string> = {
  PENDING: "待审批", RUNNING: "审批中", APPROVED: "已通过",
  REJECTED: "已拒绝", MANUAL_REVIEW: "人工复核", FAILURE: "任务失败",
};

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    PENDING:       "bg-slate-100 text-slate-600",
    RUNNING:       "bg-blue-100 text-blue-700",
    APPROVED:      "bg-emerald-100 text-emerald-700",
    REJECTED:      "bg-red-100 text-red-700",
    MANUAL_REVIEW: "bg-amber-100 text-amber-700",
    FAILURE:       "bg-red-100 text-red-600",
  };
  return (
    <span className={cn(
      "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium",
      map[status] ?? "bg-muted text-muted-foreground"
    )}>
      {status === "RUNNING" && <Loader2 className="h-3 w-3 animate-spin" />}
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

// ── Stats Card ──────────────────────────────────────────────────────────────

function StatsCard({
  title, value, sub, icon: Icon, iconBg,
}: {
  title: string; value: React.ReactNode; sub?: React.ReactNode;
  icon: React.ElementType; iconBg: string;
}) {
  return (
    <div className="studio-panel">
      <div className="studio-panel-body flex items-start justify-between gap-3">
        <div>
          <p className="text-sm text-muted-foreground">{title}</p>
          <p className="mt-1 text-3xl font-bold tabular-nums">{value}</p>
          {sub && <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>}
        </div>
        <div className={cn("flex h-11 w-11 shrink-0 items-center justify-center rounded-xl", iconBg)}>
          <Icon className="h-5 w-5" />
        </div>
      </div>
    </div>
  );
}

// ── Score Gauge (compact) ──────────────────────────────────────────────────

function ScoreChip({ score, grade }: { score: number; grade: string }) {
  const color = score >= 700 ? "text-emerald-600" : score >= 500 ? "text-amber-600" : "text-red-600";
  return (
    <span className={cn("font-semibold tabular-nums", color)}>
      {score} <span className="font-normal text-muted-foreground">({grade})</span>
    </span>
  );
}

// ── Score Breakdown ─────────────────────────────────────────────────────────

const SCORE_LABELS: Record<keyof Omit<ScoreBreakdown, "total">, string> = {
  fico: "FICO", dti: "DTI", delinq: "逾期", emp_length: "工龄",
  home: "房产", revol_util: "使用率", inquiries: "查询",
};

function ScoreBreakdownBars({ bd }: { bd: ScoreBreakdown }) {
  return (
    <div className="space-y-1.5">
      {(Object.keys(SCORE_LABELS) as Array<keyof typeof SCORE_LABELS>).map((k) => {
        const v = bd[k] ?? 0;
        return (
          <div key={k} className="flex items-center gap-2 text-xs">
            <span className="w-14 shrink-0 text-muted-foreground">{SCORE_LABELS[k]}</span>
            <div className="relative flex h-3 flex-1 items-center">
              <div className="h-1.5 w-full rounded-full bg-muted" />
              <div className={cn("absolute h-1.5 rounded-full", v > 0 ? "bg-emerald-500" : v < 0 ? "bg-red-500" : "bg-muted-foreground/20")}
                style={{ width: `${(Math.abs(v) / 400) * 100}%` }} />
            </div>
            <span className={cn("w-9 text-right tabular-nums font-medium",
              v > 0 ? "text-emerald-600" : v < 0 ? "text-red-600" : "text-muted-foreground")}>
              {v > 0 ? `+${v}` : v}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ── Approval Report (collapsible) ──────────────────────────────────────────

function ApprovalReport({ report }: { report: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-border">
      <button type="button" onClick={() => setOpen(o => !o)}
        className="flex w-full cursor-pointer items-center justify-between px-4 py-2.5 text-sm font-medium hover:bg-muted/50">
        <span className="flex items-center gap-2">
          <FileText className="h-4 w-4 text-primary" />审批报告（含政策引用）
        </span>
        {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
      </button>
      {open && (
        <div className="max-h-56 overflow-y-auto border-t border-border px-4 pb-4 pt-3">
          <div className="prose prose-sm max-w-none text-foreground [&_h2]:text-sm [&_h2]:font-semibold [&_h3]:text-xs [&_h3]:font-semibold [&_p]:text-xs [&_li]:text-xs">
            <ReactMarkdown>{report}</ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Decision Detail Modal ───────────────────────────────────────────────────

function DecisionModal({
  applicant, result, onClose, onApprove, approving,
}: {
  applicant: Applicant;
  result: ApproveStatusResponse | null;
  onClose: () => void;
  onApprove: () => void;
  approving: boolean;
}) {
  const decision = result?.decision ?? result?.applicant_status;
  const isTerminal = ["APPROVED", "REJECTED", "MANUAL_REVIEW", "FAILURE"].includes(decision ?? "");
  const isRunning = approving || result?.status === "RUNNING" || result?.status === "PENDING";

  const decisionCfg = {
    APPROVED:      { cls: "border-emerald-200 bg-emerald-50", icon: <BadgeCheck className="h-6 w-6 text-emerald-600" />, label: "审批通过", lblCls: "text-emerald-700" },
    REJECTED:      { cls: "border-red-200 bg-red-50",         icon: <XCircle className="h-6 w-6 text-red-600" />,       label: "审批拒绝", lblCls: "text-red-700" },
    MANUAL_REVIEW: { cls: "border-amber-200 bg-amber-50",     icon: <AlertCircle className="h-6 w-6 text-amber-600" />, label: "人工复核", lblCls: "text-amber-700" },
  }[decision ?? ""] ?? null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />
      <div className="relative z-10 mx-4 flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl bg-card shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <div>
            <h2 className="text-base font-semibold">{applicant.name}</h2>
            <p className="text-xs text-muted-foreground">{applicant.applicant_id}</p>
          </div>
          <div className="flex items-center gap-3">
            {applicant.status === "PENDING" && !isTerminal && (
              <Button size="sm" onClick={onApprove} disabled={isRunning} className="gap-2">
                {isRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                {isRunning ? "审批中…" : "Agent 审批"}
              </Button>
            )}
            <button type="button" onClick={onClose}
              title="关闭窗口（审批继续在后台运行）"
              className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-full hover:bg-muted">
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {/* Running */}
          {isRunning && !isTerminal && (
            <div className="rounded-xl border border-blue-200 bg-blue-50 p-4 space-y-2">
              <div className="flex items-center gap-2 text-sm font-medium text-blue-700">
                <Loader2 className="h-4 w-4 animate-spin" />Agent 正在审批，预计需要 30–90 秒…
              </div>
              <Skeleton className="h-3 w-3/4" /><Skeleton className="h-3 w-1/2" />
              <p className="text-xs text-blue-600 pt-1">
                ✓ 可以关闭此窗口，审批会在后台继续运行。重新点击该申请人即可查看最新结果。
              </p>
            </div>
          )}

          {/* Decision card */}
          {decisionCfg && isTerminal && (
            <div className={cn("rounded-xl border-2 p-5 space-y-4", decisionCfg.cls)}>
              <div className="flex items-center gap-3">
                {decisionCfg.icon}
                <div>
                  <h3 className={cn("text-base font-semibold", decisionCfg.lblCls)}>{decisionCfg.label}</h3>
                  {result?.suggested_amount != null && (
                    <p className="text-sm text-muted-foreground">
                      额度 <span className="font-semibold text-foreground">¥{result.suggested_amount.toLocaleString()}</span>
                      {result?.suggested_rate != null && <> · 利率 <span className="font-semibold">{result.suggested_rate}%</span></>}
                    </p>
                  )}
                </div>
                {result?.risk_score != null && (
                  <div className="ml-auto text-right">
                    <p className="text-2xl font-bold tabular-nums">
                      <ScoreChip score={result.risk_score} grade={result.risk_grade ?? "?"} />
                    </p>
                    <p className="text-xs text-muted-foreground">风险评分</p>
                  </div>
                )}
              </div>

              {result?.score_breakdown && (
                <div>
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">评分明细</p>
                  <ScoreBreakdownBars bd={result.score_breakdown} />
                </div>
              )}

              {result?.decision_reasons?.length ? (
                <div>
                  <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">审批依据</p>
                  <ul className="space-y-1">
                    {result.decision_reasons.map((r, i) => (
                      <li key={i} className="flex items-start gap-2 text-xs">
                        <span className="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />{r}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {result?.risk_warnings?.length ? (
                <div className="rounded-md border border-amber-200 bg-amber-50/60 p-3">
                  <p className="mb-1 text-xs font-semibold text-amber-700">风险提示</p>
                  {result.risk_warnings.map((w, i) => <p key={i} className="text-xs text-amber-700">{w}</p>)}
                </div>
              ) : null}

              {result?.approval_report && <ApprovalReport report={result.approval_report} />}
            </div>
          )}

          {/* Basic info */}
          <div className="grid grid-cols-2 gap-3 rounded-xl border border-border p-4 text-sm">
            {[
              ["申请金额", `¥${Number(applicant.requested_amount).toLocaleString()}`],
              ["申请期限", `${applicant.requested_term} 个月`],
              ["年收入",   `¥${Number(applicant.annual_income).toLocaleString()}`],
              ["FICO 评分", applicant.fico_score ?? "—"],
              ["DTI", applicant.dti != null ? `${applicant.dti}%` : "—"],
              ["职业", applicant.emp_title ?? "—"],
              ["工作年限", applicant.emp_length ?? "—"],
              ["房产状况", applicant.home_ownership ?? "—"],
              ["省市", (() => {
                const p = applicant.province ?? "";
                const c = applicant.city ?? "";
                if (!p && !c) return "—";
                if (!c || c === p) return p || "—";
                return `${p} ${c}`.trim();
              })()],
              ["产品", applicant.product_type],
            ].map(([label, val]) => (
              <div key={label as string} className="flex justify-between gap-2">
                <span className="text-muted-foreground">{label}</span>
                <span className="font-medium">{val}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Batch Progress Banner ───────────────────────────────────────────────────

function BatchBanner({ progress, onDismiss }: { progress: BatchProgress; onDismiss: () => void }) {
  const pct = progress.total ? Math.round((progress.done / progress.total) * 100) : 0;
  const done = progress.done >= progress.total;
  return (
    <div className={cn(
      "mb-4 flex items-center gap-4 rounded-xl border p-4 text-sm",
      done ? "border-emerald-200 bg-emerald-50" : "border-blue-200 bg-blue-50"
    )}>
      {done
        ? <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-600" />
        : <Loader2 className="h-5 w-5 shrink-0 animate-spin text-blue-600" />}
      <div className="flex-1">
        <p className={cn("font-medium", done ? "text-emerald-700" : "text-blue-700")}>
          {done ? `批量审批完成！共处理 ${progress.total} 条` : `批量审批进行中… ${progress.done}/${progress.total}`}
          {progress.failed > 0 && <span className="ml-2 text-red-600">（{progress.failed} 条失败）</span>}
        </p>
        <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-white/60">
          <div className={cn("h-full rounded-full transition-all duration-500", done ? "bg-emerald-500" : "bg-blue-500")}
            style={{ width: `${pct}%` }} />
        </div>
      </div>
      {done && (
        <button type="button" onClick={onDismiss} className="cursor-pointer text-muted-foreground hover:text-foreground">
          <X className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}

// ── Confirm Dialog ──────────────────────────────────────────────────────────

function ConfirmDialog({
  title, description, onConfirm, onCancel, danger = true,
}: {
  title: string; description: string;
  onConfirm: () => void; onCancel: () => void; danger?: boolean;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onCancel} />
      <div className="relative z-10 mx-4 w-full max-w-sm rounded-2xl bg-card p-6 shadow-xl">
        <div className="mb-1 flex items-center gap-2">
          <Trash2 className="h-5 w-5 text-red-500" />
          <h3 className="text-base font-semibold">{title}</h3>
        </div>
        <p className="mb-5 text-sm text-muted-foreground">{description}</p>
        <div className="flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onCancel}>取消</Button>
          <Button size="sm"
            className={danger ? "bg-red-600 hover:bg-red-700 text-white" : ""}
            onClick={onConfirm}>
            确认删除
          </Button>
        </div>
      </div>
    </div>
  );
}

// ── Generate Modal ──────────────────────────────────────────────────────────

const PROFILE_OPTIONS = [
  { value: "random",  label: "随机分布",  desc: "混合各信用档位",          color: "bg-slate-100 text-slate-700" },
  { value: "high",    label: "高信用",    desc: "FICO ≥ 720，易通过",       color: "bg-emerald-100 text-emerald-700" },
  { value: "medium",  label: "中信用",    desc: "FICO 620–719，结果混合",   color: "bg-amber-100 text-amber-700" },
  { value: "low",     label: "低信用",    desc: "FICO < 620，多数被拒",     color: "bg-red-100 text-red-700" },
];

function GenerateModal({
  onClose, onGenerate,
}: {
  onClose: () => void;
  onGenerate: (count: number, profile: string) => void;
}) {
  const [count,   setCount]   = useState(20);
  const [profile, setProfile] = useState("random");
  const [loading, setLoading] = useState(false);

  const submit = async () => {
    setLoading(true);
    await onGenerate(count, profile);
    setLoading(false);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />
      <div className="relative z-10 mx-4 w-full max-w-md rounded-2xl bg-card p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-base font-semibold">生成贷款申请人</h3>
          <button type="button" onClick={onClose} className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-full hover:bg-muted">
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Count */}
        <div className="mb-5">
          <label className="mb-1.5 block text-sm font-medium">生成数量</label>
          <div className="flex items-center gap-3">
            <input
              type="range" min={1} max={100} value={count}
              onChange={e => setCount(Number(e.target.value))}
              className="flex-1 accent-primary"
            />
            <span className="w-14 rounded-md border border-border px-2 py-1 text-center text-sm tabular-nums font-semibold">
              {count} 人
            </span>
          </div>
          <div className="mt-1 flex justify-between text-xs text-muted-foreground">
            <span>1</span><span>100</span>
          </div>
        </div>

        {/* Profile */}
        <div className="mb-6">
          <label className="mb-2 block text-sm font-medium">信用画像偏好</label>
          <div className="grid grid-cols-2 gap-2">
            {PROFILE_OPTIONS.map(opt => (
              <button
                key={opt.value} type="button"
                onClick={() => setProfile(opt.value)}
                className={cn(
                  "flex flex-col rounded-xl border-2 p-3 text-left transition-all cursor-pointer",
                  profile === opt.value ? "border-primary bg-primary/5" : "border-border hover:border-muted-foreground/40"
                )}
              >
                <span className={cn("mb-1 inline-block rounded-full px-2 py-0.5 text-xs font-medium", opt.color)}>
                  {opt.label}
                </span>
                <span className="text-xs text-muted-foreground">{opt.desc}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onClose}>取消</Button>
          <Button size="sm" onClick={submit} disabled={loading} className="gap-2">
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            生成 {count} 名申请人
          </Button>
        </div>
      </div>
    </div>
  );
}

// ── Build result from stored applicant (for processed records) ────────────

function parseDecisionReasons(raw: string | null | undefined): string[] {
  if (!raw) return [];
  // New format: JSON array
  if (raw.trim().startsWith("[")) {
    try {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed.filter(Boolean) : [raw];
    } catch { /* fall through */ }
  }
  // Legacy format: Python repr e.g. "['reason1', 'reason2']"
  const stripped = raw.replace(/^\[|\]$/g, "");
  return stripped.split("', '").map(s => s.replace(/^'|'$/g, "").trim()).filter(Boolean);
}

function buildResultFromApplicant(a: Applicant): ApproveStatusResponse {
  let sb: import("@/services/api").ScoreBreakdown | undefined;
  if (a.score_breakdown) {
    try { sb = JSON.parse(a.score_breakdown as unknown as string); } catch { /* ignore */ }
  }
  return {
    applicant_id: a.applicant_id,
    task_id: "",
    status: a.status,
    applicant_status: a.status,
    decision: a.status,
    risk_score: a.risk_score ?? undefined,
    risk_grade: a.risk_grade ?? undefined,
    suggested_amount: a.approved_amount ?? undefined,
    suggested_rate: a.approved_rate ?? undefined,
    score_breakdown: sb,
    decision_reasons: parseDecisionReasons(a.decision_reason),
    approval_report: a.approval_report ?? undefined,
  };
}

// ── Main Page ───────────────────────────────────────────────────────────────

const TERMINAL = new Set(["APPROVED", "REJECTED", "MANUAL_REVIEW", "FAILURE"]);
const POLL_MS = 2500;

export default function UnderwritingPage() {
  const [applicants, setApplicants]       = useState<Applicant[]>([]);
  const [loading, setLoading]             = useState(true);
  const [error, setError]                 = useState<string | null>(null);
  const [tab, setTab]                     = useState<"pending" | "processed">("pending");
  const [generating, setGenerating]       = useState(false);
  const [showGenerateModal, setShowGenerateModal] = useState(false);
  const [batching, setBatching]           = useState(false);
  const [batchProgress, setBatchProgress] = useState<BatchProgress | null>(null);
  // Multi-select
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // Delete
  const [deleteTarget, setDeleteTarget]       = useState<Applicant | null>(null);
  const [clearConfirm, setClearConfirm]       = useState<string | null>(null); // status or "all"
  const [deleting, setDeleting]               = useState(false);

  // Modal
  const [modalApplicant, setModalApplicant] = useState<Applicant | null>(null);

  // Background approvals: applicant_id → { taskId, result, done }
  // 独立于弹窗，关闭弹窗不中断轮询
  const [bgApprovals, setBgApprovals] = useState<
    Map<string, { taskId: string; result: ApproveStatusResponse | null; done: boolean }>
  >(new Map());
  const bgApprovalsRef = useRef(bgApprovals);
  bgApprovalsRef.current = bgApprovals;

  // Batch polling
  const batchTasksRef = useRef<BatchTask[]>([]);
  const batchPollRef  = useRef<ReturnType<typeof setInterval> | null>(null);
  // Single polling (global, not modal-scoped)
  const singlePollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchApplicants = useCallback(() => {
    setLoading(true);
    listApplicants(undefined, 200)
      .then(r => setApplicants(r.data.applicants))
      .catch(() => setError("无法加载申请人列表，请确认后端服务已启动。"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetchApplicants(); }, [fetchApplicants]);
  useEffect(() => () => {
    if (singlePollRef.current) clearInterval(singlePollRef.current);
    if (batchPollRef.current) clearInterval(batchPollRef.current);
  }, []);

  // Derived: is a specific applicant actively being approved in this session?
  const getApprovalState = (id: string) => bgApprovals.get(id) ?? null;
  const isApproving = (id: string) => {
    const s = bgApprovals.get(id);
    // taskId !== "" 才是真正提交了任务的情况；openModal 注入的条目 taskId="" 不算"审批中"
    return !!s && !s.done && s.taskId !== "";
  };

  // ── derived stats ──────────────────────────────────────────────────────
  const total     = applicants.length;
  const pending   = applicants.filter(a => a.status === "PENDING" || a.status === "RUNNING").length;
  const approved  = applicants.filter(a => a.status === "APPROVED").length;
  const rejected  = applicants.filter(a => a.status === "REJECTED").length;
  const processed = applicants.filter(a => TERMINAL.has(a.status)).length;
  const passRate  = (approved + rejected) > 0
    ? Math.round((approved / (approved + rejected)) * 100)
    : 0;

  const pendingRows   = applicants.filter(a => a.status === "PENDING" || a.status === "RUNNING");
  const processedRows = applicants.filter(a => TERMINAL.has(a.status));

  // 有审批中任务时自动刷新列表（含 /apply 提交后的 RUNNING → 终态）
  const hasRunning = applicants.some(a => a.status === "RUNNING");
  useEffect(() => {
    if (!hasRunning) return;
    const id = setInterval(() => {
      listApplicants(undefined, 200)
        .then(r => setApplicants(r.data.applicants))
        .catch(() => {});
    }, POLL_MS);
    return () => clearInterval(id);
  }, [hasRunning]);

  // ── single approve（弹窗无关，后台独立轮询）─────────────────────────────
  const startBackgroundPoll = (aid: string, tid: string) => {
    // 如果全局轮询还没启动，就启动一个共享轮询器
    if (singlePollRef.current) return; // 已有轮询在跑
    singlePollRef.current = setInterval(async () => {
      const current = bgApprovalsRef.current;
      const pending = [...current.entries()].filter(([, v]) => !v.done);
      if (pending.length === 0) {
        clearInterval(singlePollRef.current!);
        singlePollRef.current = null;
        return;
      }
      for (const [appId, { taskId: tId }] of pending) {
        try {
          const r = await getApproveStatus(appId, tId);
          const biz = r.data.applicant_status?.toUpperCase();
          const ts  = r.data.status?.toUpperCase();
          const done = TERMINAL.has(biz ?? "") || TERMINAL.has(ts ?? "");
          setBgApprovals(prev => {
            const next = new Map(prev);
            next.set(appId, { taskId: tId, result: r.data, done });
            return next;
          });
          if (done) {
            setApplicants(prev => prev.map(a =>
              a.applicant_id === appId ? { ...a, status: biz ?? a.status } : a
            ));
          }
        } catch { /* ignore transient errors */ }
      }
    }, POLL_MS);
    void tid; // used via ref
  };

  const handleApprove = async () => {
    if (!modalApplicant) return;
    const aid = modalApplicant.applicant_id;
    // 注册为进行中（显示 spinner）
    setBgApprovals(prev => new Map(prev).set(aid, { taskId: "", result: null, done: false }));
    try {
      const res = await approveApplicant(aid);
      const tid = res.data.task_id;
      setApplicants(prev => prev.map(a => a.applicant_id === aid ? { ...a, status: "RUNNING" } : a));
      setBgApprovals(prev => new Map(prev).set(aid, { taskId: tid, result: null, done: false }));
      startBackgroundPoll(aid, tid);
    } catch (e: unknown) {
      setBgApprovals(prev => { const m = new Map(prev); m.delete(aid); return m; });
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "提交审批失败");
    }
  };

  // ── batch approve ──────────────────────────────────────────────────────
  const stopBatchPoll = () => {
    if (batchPollRef.current) { clearInterval(batchPollRef.current); batchPollRef.current = null; }
  };

  const handleBatchApprove = async (ids?: string[]) => {
    const targetIds = ids ?? (selected.size > 0 ? [...selected] : undefined);
    if (!targetIds && pending === 0) return;
    setBatching(true);
    setSelected(new Set());
    try {
      const res = await batchApprove(targetIds, 50);
      const tasks = res.data.tasks;
      if (tasks.length === 0) {
        setBatching(false);
        setError("没有可审批的申请人（均非 PENDING 状态）。");
        return;
      }
      batchTasksRef.current = tasks;
      setBatchProgress({ total: tasks.length, done: 0, failed: 0 });
      setApplicants(prev => prev.map(a =>
        tasks.some(t => t.applicant_id === a.applicant_id) ? { ...a, status: "RUNNING" } : a
      ));

      // poll all tasks
      const doneSet = new Set<string>();
      stopBatchPoll();
      batchPollRef.current = setInterval(async () => {
        const remaining = tasks.filter(t => !doneSet.has(t.applicant_id));
        if (remaining.length === 0) { stopBatchPoll(); setBatching(false); return; }

        await Promise.allSettled(remaining.map(async ({ applicant_id, task_id }) => {
          try {
            const r = await getApproveStatus(applicant_id, task_id);
            const biz = r.data.applicant_status?.toUpperCase();
            const ts  = r.data.status?.toUpperCase();
            if (TERMINAL.has(biz ?? "") || TERMINAL.has(ts ?? "")) {
              doneSet.add(applicant_id);
              const failed = ts === "FAILURE" ? 1 : 0;
              setBatchProgress(p => p ? { ...p, done: p.done + 1, failed: p.failed + failed } : p);
              setApplicants(prev => prev.map(a =>
                a.applicant_id === applicant_id ? { ...a, status: biz ?? a.status } : a
              ));
            }
          } catch { /* ignore */ }
        }));

        if (doneSet.size >= tasks.length) { stopBatchPoll(); setBatching(false); }
      }, POLL_MS);
    } catch (e: unknown) {
      setBatching(false);
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "批量审批失败");
    }
  };

  // ── generate ───────────────────────────────────────────────────────────
  const handleGenerate = async (count = 20, profile = "random") => {
    setGenerating(true);
    try { await generateApplicants(count, profile); await fetchApplicants(); }
    catch { setError("生成申请人失败"); }
    finally { setGenerating(false); }
  };

  // ── reset stale ────────────────────────────────────────────────────────
  const handleReset = async (id: string) => {
    try {
      await resetApplicant(id);
      setApplicants(prev => prev.map(a => a.applicant_id === id ? { ...a, status: "MANUAL_REVIEW" } : a));
    } catch { setError("重置失败"); }
  };

  // ── delete single ──────────────────────────────────────────────────────
  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await deleteApplicant(deleteTarget.applicant_id);
      setApplicants(prev => prev.filter(a => a.applicant_id !== deleteTarget.applicant_id));
      if (modalApplicant?.applicant_id === deleteTarget.applicant_id) closeModal();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "删除失败");
    } finally {
      setDeleting(false);
      setDeleteTarget(null);
    }
  };

  // ── clear batch ─────────────────────────────────────────────────────────
  const handleClearConfirm = async () => {
    if (!clearConfirm) return;
    setDeleting(true);
    try {
      await deleteApplicantsBatch(clearConfirm === "all" ? undefined : clearConfirm);
      await fetchApplicants();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "批量删除失败");
    } finally {
      setDeleting(false);
      setClearConfirm(null);
    }
  };

  // ── open / close modal（不影响后台轮询）─────────────────────────────────
  const openModal = (a: Applicant) => {
    setModalApplicant(a);
    // 已处理申请人：注入 DB 结果到 bgApprovals
    // 若已有条目但尚未完成（stale RUNNING），也强制覆盖为终态结果
    if (TERMINAL.has(a.status)) {
      setBgApprovals(prev => {
        const existing = prev.get(a.applicant_id);
        // 只有条目已经完成（done=true）且有 result，才优先保留；否则用 DB 数据覆盖
        if (existing?.done && existing.result) return prev;
        const m = new Map(prev);
        m.set(a.applicant_id, { taskId: "", result: buildResultFromApplicant(a), done: true });
        return m;
      });
    }
  };
  const closeModal = () => setModalApplicant(null); // 轮询继续在后台跑

  // ── render table ───────────────────────────────────────────────────────
  const renderTable = (rows: Applicant[], showDecision: boolean) => {
    if (loading) return (
      <div className="space-y-2 p-4">
        {[...Array(5)].map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}
      </div>
    );
    if (rows.length === 0) return (
      <div className="flex flex-col items-center gap-3 py-16 text-center text-muted-foreground">
        <FileText className="h-10 w-10 opacity-30" />
        <p className="text-sm">{showDecision ? "暂无已处理申请" : "暂无待审批申请"}</p>
        {!showDecision && (
          <Button size="sm" variant="outline" onClick={() => setShowGenerateModal(true)} disabled={generating}>
            <Sparkles className="h-4 w-4" />立即生成
          </Button>
        )}
      </div>
    );

    const allPendingIds = rows.filter(r => r.status === "PENDING").map(r => r.applicant_id);
    const allChecked = allPendingIds.length > 0 && allPendingIds.every(id => selected.has(id));
    const someChecked = allPendingIds.some(id => selected.has(id));

    const toggleAll = () => {
      if (allChecked) {
        setSelected(prev => { const n = new Set(prev); allPendingIds.forEach(id => n.delete(id)); return n; });
      } else {
        setSelected(prev => new Set([...prev, ...allPendingIds]));
      }
    };
    const toggleOne = (id: string) => setSelected(prev => {
      const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n;
    });

    return (
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/40 text-left text-xs font-medium text-muted-foreground">
              {!showDecision && (
                <th className="w-10 px-4 py-3">
                  <input type="checkbox" checked={allChecked} ref={el => { if (el) el.indeterminate = someChecked && !allChecked; }}
                    onChange={toggleAll} className="cursor-pointer rounded" />
                </th>
              )}
              <th className="px-4 py-3">申请编号</th>
              <th className="px-4 py-3">姓名</th>
              <th className="px-4 py-3 text-right">贷款金额</th>
              <th className="px-4 py-3 text-right">信用评分</th>
              <th className="px-4 py-3">审批状态</th>
              {showDecision && <th className="px-4 py-3">审批理由</th>}
              {showDecision && <th className="px-4 py-3">处理时间</th>}
              <th className="px-4 py-3 text-right">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map(a => {
              const bgActive = isApproving(a.applicant_id);
              const isStaleRunning = a.status === "RUNNING" && !bgActive;
              const isChecked = selected.has(a.applicant_id);
              return (
                <tr
                  key={a.applicant_id}
                  onClick={() => openModal(a)}
                  className={cn("cursor-pointer transition-colors hover:bg-muted/40", isChecked && "bg-primary/[0.04]")}
                >
                  {!showDecision && (
                    <td className="px-4 py-3" onClick={e => { e.stopPropagation(); if (a.status === "PENDING") toggleOne(a.applicant_id); }}>
                      <input type="checkbox" checked={isChecked} disabled={a.status !== "PENDING"}
                        onChange={() => {}} className={cn("rounded", a.status === "PENDING" ? "cursor-pointer" : "cursor-default opacity-30")} />
                    </td>
                  )}
                  <td className="px-4 py-3 font-mono text-xs text-muted-foreground">{a.applicant_id}</td>
                  <td className="px-4 py-3 font-medium">
                    <span className="flex items-center gap-1.5">
                      {a.name}
                      {bgActive && (
                        <span className="inline-flex items-center gap-1 rounded-full bg-blue-100 px-1.5 py-0.5 text-[11px] text-blue-700">
                          <Loader2 className="h-2.5 w-2.5 animate-spin" />后台审批中
                        </span>
                      )}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">¥{Number(a.requested_amount).toLocaleString()}</td>
                  <td className="px-4 py-3 text-right">
                    {a.fico_score != null
                      ? <ScoreChip score={a.fico_score} grade={a.risk_grade ?? "?"} />
                      : <span className="text-muted-foreground">—</span>}
                  </td>
                  <td className="px-4 py-3"><StatusBadge status={a.status} /></td>
                  {showDecision && (
                    <td className="max-w-xs px-4 py-3 text-xs text-muted-foreground">
                      <span className="line-clamp-2">
                        {parseDecisionReasons(a.decision_reason).join(" · ") || "—"}
                      </span>
                    </td>
                  )}
                  {showDecision && (
                    <td className="px-4 py-3 text-xs text-muted-foreground whitespace-nowrap">
                      {a.reviewed_at ? a.reviewed_at.replace("T", " ") : "—"}
                    </td>
                  )}
                  <td className="px-4 py-3 text-right" onClick={e => e.stopPropagation()}>
                    <div className="flex items-center justify-end gap-1">
                      {isStaleRunning ? (
                        <Button size="sm" variant="outline"
                          className="border-amber-300 text-amber-700 hover:bg-amber-50 text-xs h-7"
                          onClick={() => handleReset(a.applicant_id)}>
                          重置
                        </Button>
                      ) : a.status === "PENDING" ? (
                        <Button size="sm" variant="outline" className="text-xs h-7"
                          onClick={() => openModal(a)}>
                          审批
                        </Button>
                      ) : (
                        <Button size="sm" variant="ghost" className="text-xs h-7 text-muted-foreground"
                          onClick={() => openModal(a)}>
                          详情
                        </Button>
                      )}
                      {a.status !== "RUNNING" && (
                        <Button size="sm" variant="ghost"
                          className="h-7 w-7 p-0 text-muted-foreground hover:text-red-600"
                          onClick={() => setDeleteTarget(a)}
                          title="删除">
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  };

  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader
        title="贷前授信审批"
        description="Agent 自动完成申请人信息获取、RAG 政策检索、风险评分与审批决策，支持并发批量处理。"
        extra={
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" onClick={fetchApplicants} disabled={loading}>
              <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
              刷新
            </Button>
            <Button variant="outline" size="sm" onClick={() => setShowGenerateModal(true)} disabled={generating} className="gap-1.5">
              {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Settings2 className="h-4 w-4" />}
              生成申请人
            </Button>
            {selected.size > 0 ? (
              <Button size="sm" onClick={() => handleBatchApprove([...selected])} disabled={batching} className="gap-2 bg-emerald-600 hover:bg-emerald-700">
                {batching ? <Loader2 className="h-4 w-4 animate-spin" /> : <BadgeCheck className="h-4 w-4" />}
                审批选中 ({selected.size})
              </Button>
            ) : (
              <Button size="sm" onClick={() => handleBatchApprove()} disabled={batching || pending === 0} className="gap-2">
                {batching ? <Loader2 className="h-4 w-4 animate-spin" /> : <BadgeCheck className="h-4 w-4" />}
                批量审批全部 ({pending})
              </Button>
            )}
            <div className="relative">
              <select
                className="cursor-pointer appearance-none rounded-md border border-border bg-card px-3 py-1.5 text-xs text-muted-foreground shadow-sm hover:border-red-300 hover:text-red-600 focus:outline-none"
                value=""
                onChange={e => { if (e.target.value) setClearConfirm(e.target.value); e.target.value = ""; }}
                title="清空数据"
              >
                <option value="" disabled>清空数据▾</option>
                <option value="PENDING">清空待审批</option>
                <option value="APPROVED">清空已通过</option>
                <option value="REJECTED">清空已拒绝</option>
                <option value="MANUAL_REVIEW">清空人工复核</option>
                <option value="all">清空全部（非进行中）</option>
              </select>
            </div>
          </div>
        }
      />

      {error && (
        <Alert variant="destructive" className="mb-4">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription className="flex items-center justify-between">
            {error}
            <Button variant="ghost" size="sm" onClick={() => setError(null)}>关闭</Button>
          </AlertDescription>
        </Alert>
      )}

      {/* Batch progress banner */}
      {batchProgress && (
        <BatchBanner
          progress={batchProgress}
          onDismiss={() => setBatchProgress(null)}
        />
      )}

      {/* Stats cards */}
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatsCard title="总申请数量" value={total}
          sub={`+0 待处理`}
          icon={Users} iconBg="bg-blue-100 text-blue-600" />
        <StatsCard title="待审批数量" value={pending}
          sub={selected.size > 0 ? `已勾选 ${selected.size} 个` : "点击复选框多选"}
          icon={FileText} iconBg="bg-orange-100 text-orange-600" />
        <StatsCard title="通过率" value={`${passRate}%`}
          sub={<span className="text-emerald-600">{approved} 通过</span>}
          icon={TrendingUp} iconBg="bg-emerald-100 text-emerald-600" />
        <StatsCard title="已处理数量" value={processed}
          sub={<span className="text-red-500">{rejected} 拒绝</span>}
          icon={BadgeCheck} iconBg="bg-purple-100 text-purple-600" />
      </div>

      {/* Main panel */}
      <div className="studio-panel">
        {/* Panel header */}
        <div className="studio-panel-header">
          <div className="flex items-center gap-1">
            <span className="font-medium">最近申请审批</span>
            <span className="ml-1 text-xs text-muted-foreground">管理贷款申请、执行审批流程</span>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-0 border-b border-border">
          {[
            { key: "pending",   label: `待审批 (${pending})` },
            { key: "processed", label: `已处理 (${processedRows.length})` },
          ].map(({ key, label }) => (
            <button key={key} type="button"
              onClick={() => setTab(key as typeof tab)}
              className={cn(
                "cursor-pointer px-5 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px",
                tab === key
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              )}>
              {label}
            </button>
          ))}
        </div>

        {/* Table */}
        <div className="studio-panel-body p-0">
          {tab === "pending"
            ? renderTable(pendingRows, false)
            : renderTable(processedRows, true)}
        </div>
      </div>

      {/* Single approval modal */}
      {modalApplicant && (() => {
        const bgState = getApprovalState(modalApplicant.applicant_id);
        return (
          <DecisionModal
            applicant={modalApplicant}
            result={bgState?.result ?? null}
            onClose={closeModal}
            onApprove={handleApprove}
            approving={!!bgState && !bgState.done}
          />
        );
      })()}

      {/* Delete single confirm */}
      {deleteTarget && (
        <ConfirmDialog
          title="删除申请人"
          description={`确认删除申请人「${deleteTarget.name}」（${deleteTarget.applicant_id}）？此操作不可撤销。`}
          onConfirm={handleDeleteConfirm}
          onCancel={() => setDeleteTarget(null)}
        />
      )}

      {/* Clear batch confirm */}
      {clearConfirm && (
        <ConfirmDialog
          title="批量清空数据"
          description={
            clearConfirm === "all"
              ? "确认清空全部非进行中的申请人数据？此操作不可撤销。"
              : `确认清空所有「${STATUS_LABEL[clearConfirm] ?? clearConfirm}」状态的申请人？此操作不可撤销。`
          }
          onConfirm={handleClearConfirm}
          onCancel={() => setClearConfirm(null)}
        />
      )}

      {/* Deleting overlay */}
      {deleting && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20">
          <div className="flex items-center gap-3 rounded-xl bg-card px-6 py-4 shadow-xl">
            <Loader2 className="h-5 w-5 animate-spin text-primary" />
            <span className="text-sm font-medium">正在删除…</span>
          </div>
        </div>
      )}

      {/* Generate modal */}
      {showGenerateModal && (
        <GenerateModal
          onClose={() => setShowGenerateModal(false)}
          onGenerate={handleGenerate}
        />
      )}
    </div>
  );
}
