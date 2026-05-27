import { Link, useLocation } from "react-router-dom";
import {
  Banknote,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  LayoutDashboard,
  Search,
  Shield,
  UserPlus,
} from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

const navItems = [
  { path: "/", icon: Search, label: "智能分析" },
  { path: "/apply", icon: UserPlus, label: "贷款申请" },
  { path: "/dashboard", icon: LayoutDashboard, label: "数据概览" },
  { path: "/strategies", icon: Shield, label: "策略管理" },
  { path: "/underwriting", icon: ClipboardCheck, label: "贷前授信" },
];

const pageTitles: Record<string, string> = {
  "/": "智能分析",
  "/apply": "在线贷款申请",
  "/dashboard": "数据概览",
  "/strategies": "策略管理",
  "/underwriting": "贷前授信审批",
};

export function AppShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const location = useLocation();
  const title = pageTitles[location.pathname] ?? "信贷风控";

  return (
    <div className="min-h-screen bg-background">
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex flex-col border-r border-border bg-card transition-[width] duration-150",
          collapsed ? "w-16" : "w-60"
        )}
      >
        <div className="flex h-[52px] items-center gap-2.5 border-b border-border px-3">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Banknote className="h-4 w-4" />
          </div>
          {!collapsed && (
            <div>
              <p className="text-sm font-semibold leading-tight">信贷风控 Agent</p>
              <p className="text-[11px] text-muted-foreground">Credit Risk Platform</p>
            </div>
          )}
        </div>

        {!collapsed && (
          <p className="px-3 pb-1 pt-4 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            导航
          </p>
        )}

        <nav className="flex flex-1 flex-col gap-0.5 px-2 py-1">
          {navItems.map(({ path, icon: Icon, label }) => {
            const active = location.pathname === path;
            return (
              <Link
                key={path}
                to={path}
                title={collapsed ? label : undefined}
                className={cn(
                  "relative flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm font-medium transition-colors",
                  active
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
              >
                {active && (
                  <span className="absolute -left-2 top-1.5 bottom-1.5 w-0.5 rounded-r bg-primary" />
                )}
                <Icon className="h-4 w-4 shrink-0" />
                {!collapsed && <span>{label}</span>}
              </Link>
            );
          })}
        </nav>

        <div className="border-t border-border p-2">
          <Button
            variant="outline"
            size="sm"
            className="w-full"
            onClick={() => setCollapsed((c) => !c)}
            aria-label={collapsed ? "展开侧栏" : "收起侧栏"}
          >
            {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
          </Button>
        </div>
      </aside>

      <div className={cn("flex min-h-screen flex-col transition-[margin] duration-150", collapsed ? "ml-16" : "ml-60")}>
        <header className="sticky top-0 z-30 flex h-[52px] items-center justify-between border-b border-border bg-card px-6">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <span>信贷风控</span>
            <span>/</span>
            <span className="font-semibold text-foreground">{title}</span>
          </div>
          <span className="text-xs text-muted-foreground">LangGraph · Multi-Agent</span>
        </header>
        <main className="flex flex-1 flex-col overflow-hidden p-6">{children}</main>
      </div>
    </div>
  );
}
