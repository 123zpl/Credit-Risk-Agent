import { useState, type FormEvent } from "react";
import { Loader2, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const EXAMPLE_QUERIES = [
  "各信用评级的逾期率是多少？",
  "逾期率上升的主要原因是什么？",
  "当前贷款利率是否合规？",
  "给出降低逾期率的风控策略建议",
  "你好",
];

interface Props {
  onSubmit: (query: string) => void;
  loading: boolean;
}

export default function QueryInput({ onSubmit, loading }: Props) {
  const [value, setValue] = useState("");

  const handleSubmit = (e?: FormEvent) => {
    e?.preventDefault();
    const q = value.trim();
    if (q) {
      onSubmit(q);
      setValue("");
    }
  };

  return (
    <section className="rounded-lg border border-border bg-card p-6 focus-within:border-primary/40 focus-within:ring-2 focus-within:ring-primary/10">
      <div className="mb-4 inline-flex items-center gap-2 rounded-full bg-muted px-3 py-1 text-xs text-muted-foreground">
        <span
          className={cn(
            "h-2 w-2 rounded-full",
            loading ? "animate-pulse bg-amber-500" : "bg-emerald-500"
          )}
        />
        {loading ? "Agent 正在分析…" : "系统就绪"}
      </div>

      <h2 className="text-lg font-semibold tracking-tight">向风控 Agent 提问</h2>
      <p className="mt-1 mb-5 text-sm text-muted-foreground">
        自然语言输入，自动识别意图并调度 Multi-Agent 生成分析报告
      </p>

      <form onSubmit={handleSubmit} className="flex gap-2">
        <Input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="例如：各信用评级的逾期率是多少？"
          className="h-11 flex-1"
          disabled={loading}
        />
        <Button type="submit" variant="cta" size="lg" disabled={loading} className="shrink-0 px-5">
          {loading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Search className="h-4 w-4" />
          )}
          开始分析
        </Button>
      </form>

      <div className="mt-3.5 flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-xs text-muted-foreground">示例</span>
        {EXAMPLE_QUERIES.map((q) => (
          <button
            key={q}
            type="button"
            disabled={loading}
            onClick={() => !loading && onSubmit(q)}
            className="cursor-pointer rounded-full border border-transparent bg-muted px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:border-primary/20 hover:bg-primary/5 hover:text-primary disabled:opacity-50"
          >
            {q}
          </button>
        ))}
      </div>
    </section>
  );
}
