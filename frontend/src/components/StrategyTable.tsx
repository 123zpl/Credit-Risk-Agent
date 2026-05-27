import { useState } from "react";
import { CheckCircle, StopCircle, Trash2, Eye } from "lucide-react";
import { toast } from "sonner";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Strategy } from "@/services/api";
import { updateStrategy, deleteStrategy } from "@/services/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

interface Props {
  strategies: Strategy[];
  loading: boolean;
  onRefresh: () => void;
}

const statusConfig: Record<
  string,
  { label: string; variant: "secondary" | "default" | "success" | "destructive" }
> = {
  DRAFT:          { label: "草稿",   variant: "secondary" },
  PENDING_REVIEW: { label: "待审批", variant: "default" },
  ACTIVE:         { label: "已启用", variant: "success" },
  DISABLED:       { label: "已禁用", variant: "destructive" },
};

type PendingAction =
  | { type: "status"; id: string; status: string }
  | { type: "delete"; id: string; name: string }
  | { type: "batch_delete"; ids: string[] };

export default function StrategyTable({ strategies, loading, onRefresh }: Props) {
  const [pending, setPending]       = useState<PendingAction | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [detail, setDetail]         = useState<Strategy | null>(null);
  const [selected, setSelected]     = useState<Set<string>>(new Set());

  // ── Selection helpers ───────────────────────────────────────
  const allIds = strategies.map((s) => s.strategy_id);
  const allChecked = allIds.length > 0 && allIds.every((id) => selected.has(id));
  const someChecked = allIds.some((id) => selected.has(id));

  const toggleAll = () => {
    if (allChecked) {
      setSelected(new Set());
    } else {
      setSelected(new Set(allIds));
    }
  };

  const toggleOne = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  // ── Confirm handler ─────────────────────────────────────────
  const handleConfirm = async () => {
    if (!pending) return;
    setSubmitting(true);
    try {
      if (pending.type === "status") {
        await updateStrategy(pending.id, pending.status);
        toast.success("状态已更新");
      } else if (pending.type === "delete") {
        await deleteStrategy(pending.id);
        toast.success("策略已删除");
        setSelected((prev) => { const n = new Set(prev); n.delete(pending.id); return n; });
      } else {
        // batch delete
        const results = await Promise.allSettled(
          pending.ids.map((id) => deleteStrategy(id))
        );
        const failed = results.filter((r) => r.status === "rejected").length;
        if (failed === 0) toast.success(`已删除 ${pending.ids.length} 条策略`);
        else toast.warning(`${pending.ids.length - failed} 条成功，${failed} 条失败`);
        setSelected(new Set());
      }
      onRefresh();
    } catch {
      toast.error(pending.type === "status" ? "更新失败" : "删除失败");
    } finally {
      setSubmitting(false);
      setPending(null);
    }
  };

  if (loading) {
    return (
      <div className="space-y-2 p-4">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  return (
    <>
      {/* ── Batch toolbar ──────────────────────────────────── */}
      {someChecked && (
        <div className="flex items-center gap-3 border-b border-border bg-muted/40 px-4 py-2">
          <span className="text-sm text-muted-foreground">
            已选 <span className="font-semibold text-foreground">{selected.size}</span> 条
          </span>
          <Button
            size="sm"
            variant="destructive"
            className="gap-1.5"
            onClick={() =>
              setPending({ type: "batch_delete", ids: Array.from(selected) })
            }
          >
            <Trash2 className="h-3.5 w-3.5" />
            批量删除
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="text-muted-foreground"
            onClick={() => setSelected(new Set())}
          >
            取消选择
          </Button>
        </div>
      )}

      <Table>
        <TableHeader>
          <TableRow>
            {/* Select-all checkbox */}
            <TableHead className="w-10 pr-0">
              <input
                type="checkbox"
                checked={allChecked}
                ref={(el) => { if (el) el.indeterminate = someChecked && !allChecked; }}
                onChange={toggleAll}
                className="h-4 w-4 cursor-pointer rounded border-border accent-primary"
                aria-label="全选"
              />
            </TableHead>
            <TableHead className="w-[160px]">策略名称</TableHead>
            <TableHead className="w-[260px] max-w-[260px]">描述</TableHead>
            <TableHead className="w-[88px]">状态</TableHead>
            <TableHead className="w-[88px]">来源</TableHead>
            <TableHead className="w-[140px]">创建时间</TableHead>
            <TableHead className="w-[200px]">操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {strategies.length === 0 ? (
            <TableRow>
              <TableCell colSpan={7} className="h-24 text-center text-muted-foreground">
                暂无策略数据
              </TableCell>
            </TableRow>
          ) : (
            strategies.map((record) => {
              const cfg = statusConfig[record.status] ?? {
                label: record.status,
                variant: "secondary" as const,
              };
              const isSelected = selected.has(record.strategy_id);
              return (
                <TableRow
                  key={record.strategy_id}
                  className={cn(isSelected && "bg-primary/5")}
                >
                  {/* Row checkbox */}
                  <TableCell className="pr-0">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleOne(record.strategy_id)}
                      className="h-4 w-4 cursor-pointer rounded border-border accent-primary"
                      aria-label={`选择 ${record.name}`}
                    />
                  </TableCell>

                  <TableCell className="font-medium">{record.name}</TableCell>

                  {/* Description – truncated, click to open detail */}
                  <TableCell className="w-[260px] max-w-[260px]">
                    <button
                      type="button"
                      onClick={() => setDetail(record)}
                      className="line-clamp-2 w-full cursor-pointer text-left text-sm text-muted-foreground hover:text-foreground hover:underline"
                      title="点击查看完整内容"
                    >
                      {record.description?.slice(0, 60) ?? "—"}
                      {(record.description?.length ?? 0) > 60 ? "…" : ""}
                    </button>
                  </TableCell>

                  <TableCell>
                    <Badge variant={cfg.variant}>{cfg.label}</Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {record.created_by === "agent" ? "Agent 生成" : "人工创建"}
                  </TableCell>
                  <TableCell className="tabular-nums text-xs text-muted-foreground">
                    {record.created_at}
                  </TableCell>

                  <TableCell>
                    <div className="flex items-center gap-1">
                      {/* Detail */}
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 px-2 text-xs"
                        onClick={() => setDetail(record)}
                      >
                        <Eye className="h-3 w-3" />
                        详情
                      </Button>

                      {/* Enable */}
                      {record.status !== "ACTIVE" && (
                        <Button
                          size="sm"
                          variant="cta"
                          className="h-7 px-2 text-xs"
                          onClick={() =>
                            setPending({ type: "status", id: record.strategy_id, status: "ACTIVE" })
                          }
                        >
                          <CheckCircle className="h-3 w-3" />
                          启用
                        </Button>
                      )}

                      {/* Disable */}
                      {record.status !== "DISABLED" && (
                        <Button
                          size="sm"
                          variant="destructive"
                          className="h-7 px-2 text-xs"
                          onClick={() =>
                            setPending({ type: "status", id: record.strategy_id, status: "DISABLED" })
                          }
                        >
                          <StopCircle className="h-3 w-3" />
                          禁用
                        </Button>
                      )}

                      {/* Delete – icon only */}
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                        onClick={() =>
                          setPending({ type: "delete", id: record.strategy_id, name: record.name })
                        }
                        aria-label="删除"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              );
            })
          )}
        </TableBody>
      </Table>

      {/* ── Status / Delete Confirm Dialog ─────────────────────── */}
      <AlertDialog open={!!pending} onOpenChange={(o) => !o && setPending(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {pending?.type === "batch_delete"
                ? `批量删除 ${pending.ids.length} 条策略`
                : pending?.type === "delete"
                ? "确认删除"
                : "确认操作"}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {pending?.type === "batch_delete"
                ? `确认删除已选的 ${pending.ids.length} 条策略？此操作不可撤销。`
                : pending?.type === "delete"
                ? `确认删除策略「${pending.name}」？此操作不可撤销。`
                : `确认将策略状态变更为「${
                    pending ? statusConfig[(pending as { status: string }).status]?.label ?? (pending as { status: string }).status : ""
                  }」？`}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={submitting}>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirm}
              disabled={submitting}
              className={
                pending?.type === "delete" || pending?.type === "batch_delete"
                  ? "bg-destructive hover:bg-destructive/90"
                  : ""
              }
            >
              {pending?.type === "batch_delete"
                ? `删除 ${pending.ids.length} 条`
                : pending?.type === "delete"
                ? "删除"
                : "确认"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* ── Detail Modal ────────────────────────────────────────── */}
      <Dialog open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-base">
              {detail?.name}
              {detail && (
                <Badge variant={statusConfig[detail.status]?.variant ?? "secondary"}>
                  {statusConfig[detail.status]?.label ?? detail.status}
                </Badge>
              )}
            </DialogTitle>
          </DialogHeader>

          <div className="mt-1 flex flex-wrap gap-x-6 gap-y-1 border-b border-border pb-3 text-xs text-muted-foreground">
            <span>来源：{detail?.created_by === "agent" ? "Agent 生成" : "人工创建"}</span>
            <span>创建时间：{detail?.created_at}</span>
            {detail?.approved_by && <span>审批人：{detail.approved_by}</span>}
          </div>

          <ScrollArea className="max-h-[60vh] pr-2">
            <article className="prose prose-sm max-w-none text-sm leading-relaxed text-foreground
              [&_code]:rounded [&_code]:bg-muted [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:text-xs
              [&_table]:w-full [&_table]:border-collapse [&_table]:rounded-lg [&_table]:border [&_table]:border-border [&_table]:text-xs
              [&_thead]:bg-muted [&_th]:border-b [&_th]:border-border [&_th]:px-3 [&_th]:py-2 [&_th]:text-left [&_th]:text-[11px] [&_th]:font-semibold [&_th]:uppercase [&_th]:tracking-wider [&_th]:text-muted-foreground
              [&_td]:border-b [&_td]:border-border/50 [&_td]:px-3 [&_td]:py-2 [&_tr:last-child_td]:border-b-0 [&_tr:hover_td]:bg-muted/40">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {detail?.description ?? ""}
              </ReactMarkdown>
            </article>
          </ScrollArea>
        </DialogContent>
      </Dialog>
    </>
  );
}
