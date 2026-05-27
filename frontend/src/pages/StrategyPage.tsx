import { useEffect, useState } from "react";
import { AlertCircle, RefreshCw } from "lucide-react";
import PageHeader from "@/components/PageHeader";
import StrategyTable from "@/components/StrategyTable";
import { StudioPanel } from "@/components/layout/StudioPanel";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { getStrategies } from "@/services/api";
import type { Strategy } from "@/services/api";

export default function StrategyPage() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("all");

  const fetchStrategies = () => {
    setLoading(true);
    setError(null);
    getStrategies(statusFilter === "all" ? undefined : statusFilter)
      .then((res) => setStrategies(res.data.strategies))
      .catch(() => setError("无法加载策略列表，请确认后端服务已启动。"))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchStrategies();
  }, [statusFilter]);

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="策略管理"
        description="查看、启用或禁用 Agent 生成的风控策略，支持按状态筛选。"
        extra={
          <div className="flex flex-wrap items-center gap-2">
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="w-[140px]">
                <SelectValue placeholder="筛选状态" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部状态</SelectItem>
                <SelectItem value="DRAFT">草稿</SelectItem>
                <SelectItem value="PENDING_REVIEW">待审批</SelectItem>
                <SelectItem value="ACTIVE">已启用</SelectItem>
                <SelectItem value="DISABLED">已禁用</SelectItem>
              </SelectContent>
            </Select>
            <Button variant="outline" onClick={fetchStrategies}>
              <RefreshCw className="h-4 w-4" />
              刷新
            </Button>
          </div>
        }
      />

      {error && (
        <Alert variant="destructive" className="mb-4">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <StudioPanel bodyClassName="p-0">
        <StrategyTable strategies={strategies} loading={loading} onRefresh={fetchStrategies} />
      </StudioPanel>
    </div>
  );
}
