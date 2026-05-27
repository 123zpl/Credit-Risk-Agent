import { useCallback, useEffect, useRef, useState } from "react";
import {
  Bot,
  ChevronDown,
  ChevronRight,
  Loader2,
  MessageSquarePlus,
  Send,
  Sparkles,
  Trash2,
  User,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  analyzeQuery,
  getSessions,
  getSessionMessages,
  deleteSession,
} from "@/services/api";
import type { ExecutionLog, SessionSummary } from "@/services/api";
import { cn } from "@/lib/utils";
import AgentTimeline from "@/components/AgentTimeline";

// ── Types ────────────────────────────────────────────────────────

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  intent?: string;
  latency?: number;
  logs?: ExecutionLog[];
  loading?: boolean;
}

// ── Constants ────────────────────────────────────────────────────

const INTENT_META: Record<string, { label: string; cls: string }> = {
  data_query:    { label: "数据查询", cls: "bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300" },
  risk_analysis: { label: "风险分析", cls: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300" },
  compliance:    { label: "合规检查", cls: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300" },
  strategy:      { label: "策略建议", cls: "bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300" },
  chitchat:      { label: "对话", cls: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300" },
  direct_reply:  { label: "对话", cls: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300" },
  underwriting:  { label: "贷前授信", cls: "bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300" },
};

const EXAMPLES = [
  "各信用评级的逾期率分别是多少？",
  "花呗和借呗的资产质量有何差异？",
  "逾期率上升的主要原因是什么？",
  "给出降低高风险客群逾期率的风控策略",
  "当前贷款利率设置是否符合监管要求？",
];

// ── Helpers ──────────────────────────────────────────────────────

function getApiErrorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (err.response?.status === 409) return "该会话正在分析中，请稍后再试";
    if (err.code === "ECONNABORTED") return "分析超时，请稍后重试";
    if (!err.response) return "无法连接后端，请确认服务已启动";
    return err.message;
  }
  if (err instanceof Error) return err.message;
  return "分析请求失败，请重试";
}

function formatRelativeTime(ts: string): string {
  if (!ts) return "";
  try {
    const d = new Date(ts);
    const diff = Date.now() - d.getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "刚刚";
    if (mins < 60) return `${mins} 分钟前`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours} 小时前`;
    const days = Math.floor(hours / 24);
    return `${days} 天前`;
  } catch {
    return "";
  }
}

// ── Collapsible Agent Timeline ───────────────────────────────────

function CollapsibleTimeline({ logs }: { logs: ExecutionLog[] }) {
  const [open, setOpen] = useState(false);
  if (!logs?.length) return null;

  return (
    <div className="mt-3 border-t border-border/50 pt-3">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1.5 rounded-full border border-border/80 bg-muted/50 px-3 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        {open ? (
          <ChevronDown className="h-3 w-3" />
        ) : (
          <ChevronRight className="h-3 w-3" />
        )}
        <span>Agent 执行链路</span>
        <span className="rounded-full bg-border/80 px-1.5 py-0.5 font-mono text-[10px] leading-none">
          {logs.length} 步
        </span>
      </button>
      {open && (
        <div className="mt-2 pl-1">
          <AgentTimeline logs={logs} />
        </div>
      )}
    </div>
  );
}

// ── Assistant Bubble ─────────────────────────────────────────────

function AssistantBubble({ msg }: { msg: ChatMessage }) {
  const meta = msg.intent ? INTENT_META[msg.intent] : null;

  return (
    <div className="group flex gap-3">
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 ring-1 ring-primary/20">
        <Bot className="h-3.5 w-3.5 text-primary" />
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-foreground">风控 Agent</span>
          {meta && (
            <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium leading-none", meta.cls)}>
              {meta.label}
            </span>
          )}
          {!!msg.latency && msg.latency > 0 && (
            <span className="ml-auto text-[11px] tabular-nums text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
              {(msg.latency / 1000).toFixed(1)}s
            </span>
          )}
        </div>
        {msg.loading ? (
          <div className="space-y-2 pt-1">
            <Skeleton className="h-3.5 w-3/4 rounded" />
            <Skeleton className="h-3.5 w-full rounded" />
            <Skeleton className="h-3.5 w-2/3 rounded" />
            <p className="mt-1 animate-pulse text-xs text-muted-foreground">
              Agent 正在思考中…
            </p>
          </div>
        ) : (
          <>
            <article className="report-markdown prose prose-sm max-w-none text-sm leading-relaxed text-foreground [&_code:not(pre_code)]:rounded [&_code:not(pre_code)]:bg-muted [&_code:not(pre_code)]:px-1.5 [&_code:not(pre_code)]:py-0.5 [&_code:not(pre_code)]:text-xs [&_code:not(pre_code)]:font-mono [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:bg-muted [&_pre]:p-3 [&_pre]:text-xs [&_table]:my-2 [&_table]:w-full [&_table]:border-collapse [&_table]:overflow-hidden [&_table]:rounded-lg [&_table]:border [&_table]:border-border [&_table]:text-xs [&_thead]:bg-muted [&_th]:border-b [&_th]:border-border [&_th]:px-3 [&_th]:py-2 [&_th]:text-left [&_th]:text-[11px] [&_th]:font-semibold [&_th]:uppercase [&_th]:tracking-wider [&_th]:text-muted-foreground [&_td]:border-b [&_td]:border-border/50 [&_td]:px-3 [&_td]:py-2 [&_td]:tabular-nums [&_tr:last-child_td]:border-b-0 [&_tr:hover_td]:bg-muted/40">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
            </article>
            {msg.logs && msg.logs.length > 0 && (
              <CollapsibleTimeline logs={msg.logs} />
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ── User Bubble ──────────────────────────────────────────────────

function UserBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-end gap-3">
      <div className="max-w-[72%] rounded-2xl rounded-tr-md bg-muted px-4 py-2.5 text-sm leading-relaxed text-foreground ring-1 ring-border/60">
        {content}
      </div>
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted ring-1 ring-border">
        <User className="h-3.5 w-3.5 text-muted-foreground" />
      </div>
    </div>
  );
}

// ── Empty State ──────────────────────────────────────────────────

function EmptyState({
  onSelect,
  loading,
}: {
  onSelect: (q: string) => void;
  loading: boolean;
}) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-8 py-12 text-center">
      <div className="flex flex-col items-center gap-4">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 shadow-inner ring-1 ring-primary/20">
          <Sparkles className="h-7 w-7 text-primary" />
        </div>
        <div className="space-y-1">
          <h2 className="text-lg font-semibold tracking-tight text-foreground">
            信贷风控智能分析
          </h2>
          <p className="max-w-md text-sm text-muted-foreground">
            使用自然语言提问，Multi-Agent 自动完成数据查询 · 风险归因 ·
            策略建议 · 合规审查
          </p>
        </div>
      </div>
      <div className="flex flex-wrap justify-center gap-2">
        {EXAMPLES.map((q) => (
          <button
            key={q}
            type="button"
            disabled={loading}
            onClick={() => onSelect(q)}
            className="cursor-pointer rounded-full border border-border bg-card px-3.5 py-1.5 text-sm text-muted-foreground shadow-sm transition-all hover:border-primary/40 hover:bg-primary/5 hover:text-primary hover:shadow-none disabled:cursor-not-allowed disabled:opacity-50"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Chat Input ───────────────────────────────────────────────────

interface ChatInputProps {
  onSubmit: (q: string) => void;
  loading: boolean;
  sessionId?: string;
}

function ChatInput({ onSubmit, loading, sessionId }: ChatInputProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const submit = () => {
    const q = value.trim();
    if (!q || loading) return;
    onSubmit(q);
    setValue("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const autoResize = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  };

  return (
    <div className="border-t border-border bg-background/95 px-4 py-3 backdrop-blur supports-[backdrop-filter]:bg-background/80">
      <div className="mx-auto max-w-3xl space-y-1.5">
        <div
          className={cn(
            "flex items-end gap-2 rounded-xl border bg-card px-3 py-2 shadow-sm transition-all",
            loading
              ? "border-border opacity-90"
              : "border-border focus-within:border-primary/50 focus-within:ring-2 focus-within:ring-primary/10"
          )}
        >
          <textarea
            ref={textareaRef}
            rows={1}
            value={value}
            disabled={loading}
            onChange={(e) => {
              setValue(e.target.value);
              autoResize();
            }}
            onKeyDown={handleKeyDown}
            placeholder="向风控 Agent 提问… （Enter 发送，Shift+Enter 换行）"
            className="min-h-[32px] flex-1 resize-none bg-transparent py-1 text-sm leading-relaxed text-foreground outline-none placeholder:text-muted-foreground/70 disabled:opacity-50"
          />
          <Button
            type="button"
            size="sm"
            disabled={loading || !value.trim()}
            onClick={submit}
            className="h-8 w-8 shrink-0 rounded-lg p-0"
          >
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </Button>
        </div>
        <div className="flex items-center gap-2 px-1">
          <span
            className={cn(
              "h-1.5 w-1.5 rounded-full transition-colors",
              loading ? "animate-pulse bg-amber-400" : "bg-emerald-400"
            )}
          />
          <span className="text-[11px] text-muted-foreground">
            {loading ? "Agent 分析中…" : "系统就绪"}
          </span>
          {sessionId && (
            <span className="ml-auto font-mono text-[11px] text-muted-foreground/60">
              会话 {sessionId.slice(0, 8)}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Session Sidebar ──────────────────────────────────────────────

interface SessionSidebarProps {
  sessions: SessionSummary[];
  activeSessionId: string | undefined;
  onNewSession: () => void;
  onSelectSession: (id: string) => void;
  onDeleteSession: (id: string) => void;
  loading: boolean;
}

function SessionSidebar({
  sessions,
  activeSessionId,
  onNewSession,
  onSelectSession,
  onDeleteSession,
  loading,
}: SessionSidebarProps) {
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    if (!window.confirm("确认删除该会话？此操作不可撤销。")) return;
    setDeletingId(id);
    try {
      await deleteSession(id);
      onDeleteSession(id);
      toast.success("会话已删除");
    } catch {
      toast.error("删除失败，请重试");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="flex h-full w-56 shrink-0 flex-col border-r border-border bg-muted/30">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-3 border-b border-border/60">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
          会话列表
        </span>
        <button
          type="button"
          onClick={onNewSession}
          disabled={loading}
          title="新建会话"
          className="flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-40"
        >
          <MessageSquarePlus className="h-4 w-4" />
        </button>
      </div>

      {/* Session list */}
      <div className="flex-1 overflow-y-auto py-1">
        {sessions.length === 0 ? (
          <p className="px-3 py-4 text-center text-xs text-muted-foreground/60">
            暂无历史会话
          </p>
        ) : (
          sessions.map((s) => (
            <div
              key={s.session_id}
              onClick={() => onSelectSession(s.session_id)}
              className={cn(
                "group relative flex cursor-pointer flex-col gap-0.5 px-3 py-2.5 transition-colors hover:bg-muted/60",
                activeSessionId === s.session_id &&
                  "bg-primary/8 border-r-2 border-primary"
              )}
            >
              {/* Preview text */}
              <p
                className={cn(
                  "truncate text-xs font-medium leading-snug pr-5",
                  activeSessionId === s.session_id
                    ? "text-foreground"
                    : "text-muted-foreground"
                )}
              >
                {s.preview}
              </p>

              {/* Meta row */}
              <div className="flex items-center gap-1.5">
                <span className="text-[10px] text-muted-foreground/60 tabular-nums">
                  {formatRelativeTime(s.last_active)}
                </span>
                {s.message_count > 0 && (
                  <span className="rounded-full bg-border/70 px-1.5 py-px text-[10px] text-muted-foreground/70 tabular-nums">
                    {s.message_count} 条
                  </span>
                )}
              </div>

              {/* Delete button */}
              <button
                type="button"
                onClick={(e) => handleDelete(e, s.session_id)}
                disabled={deletingId === s.session_id}
                title="删除会话"
                className="absolute right-2 top-1/2 -translate-y-1/2 flex h-5 w-5 items-center justify-center rounded text-muted-foreground/30 opacity-0 transition-all group-hover:opacity-100 hover:bg-destructive/10 hover:text-destructive disabled:opacity-30"
              >
                {deletingId === s.session_id ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Trash2 className="h-3 w-3" />
                )}
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

// ── Main Page ────────────────────────────────────────────────────

export default function AnalysisPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Load session list on mount
  const refreshSessions = useCallback(async () => {
    setSessionsLoading(true);
    try {
      const res = await getSessions();
      setSessions(res.data.sessions);
    } catch {
      // silently fail
    } finally {
      setSessionsLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshSessions();
  }, [refreshSessions]);

  // Auto-scroll to latest message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Switch to a historical session
  const handleSelectSession = useCallback(async (id: string) => {
    if (id === sessionId) return;
    setSessionId(id);
    setMessages([]);
    try {
      const res = await getSessionMessages(id);
      const loaded: ChatMessage[] = res.data.messages.map((m, i) => ({
        id: `${id}-${i}`,
        role: m.role,
        content: m.content,
        intent: m.intent || undefined,
      }));
      setMessages(loaded);
    } catch {
      toast.error("加载会话历史失败");
    }
  }, [sessionId]);

  // Create a new blank session
  const handleNewSession = useCallback(() => {
    setSessionId(undefined);
    setMessages([]);
  }, []);

  // Remove deleted session from list; if active, create new session
  const handleDeleteSession = useCallback((id: string) => {
    setSessions((prev) => prev.filter((s) => s.session_id !== id));
    if (id === sessionId) {
      setSessionId(undefined);
      setMessages([]);
    }
  }, [sessionId]);

  const handleSubmit = useCallback(
    async (query: string) => {
      const userId = crypto.randomUUID();
      const loadingId = crypto.randomUUID();

      const userMsg: ChatMessage = { id: userId, role: "user", content: query };
      const loadingMsg: ChatMessage = {
        id: loadingId,
        role: "assistant",
        content: "",
        loading: true,
      };

      setMessages((prev) => [...prev, userMsg, loadingMsg]);
      setLoading(true);

      try {
        const res = await analyzeQuery({ query, session_id: sessionId });
        const data = res.data;
        const newSid = data.session_id;
        setSessionId(newSid);

        setMessages((prev) =>
          prev.map((m) =>
            m.id === loadingId
              ? {
                  ...m,
                  loading: false,
                  content: data.report,
                  intent: data.intent,
                  latency: data.total_latency_ms,
                  logs: data.execution_log,
                }
              : m
          )
        );

        // Refresh session list to include new/updated session
        refreshSessions();
      } catch (err: unknown) {
        const msg = getApiErrorMessage(err);
        if (axios.isAxiosError(err) && err.response?.status === 409) {
          toast.warning(msg);
        } else {
          toast.error(msg);
        }
        setMessages((prev) => prev.filter((m) => m.id !== loadingId));
      } finally {
        setLoading(false);
      }
    },
    [sessionId, refreshSessions]
  );

  const hasMessages = messages.length > 0;

  return (
    <div className="-mx-6 -my-6 flex overflow-hidden" style={{ height: "calc(100vh - 52px)" }}>
      {/* Left sidebar — session list */}
      <SessionSidebar
        sessions={sessions}
        activeSessionId={sessionId}
        onNewSession={handleNewSession}
        onSelectSession={handleSelectSession}
        onDeleteSession={handleDeleteSession}
        loading={loading || sessionsLoading}
      />

      {/* Right — chat area */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Scrollable message area */}
        <div className="flex flex-1 flex-col overflow-y-auto scroll-smooth">
          <div className="mx-auto w-full max-w-3xl flex-1 px-6 py-6">
            {hasMessages ? (
              <div className="flex flex-col gap-5">
                {messages.map((msg) =>
                  msg.role === "user" ? (
                    <UserBubble key={msg.id} content={msg.content} />
                  ) : (
                    <AssistantBubble key={msg.id} msg={msg} />
                  )
                )}
              </div>
            ) : (
              <EmptyState onSelect={handleSubmit} loading={loading} />
            )}
            <div ref={bottomRef} className="h-px" />
          </div>
        </div>

        {/* Sticky bottom input */}
        <ChatInput onSubmit={handleSubmit} loading={loading} sessionId={sessionId} />
      </div>
    </div>
  );
}
