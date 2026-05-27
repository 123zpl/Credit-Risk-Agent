import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import AnalysisPage from "@/pages/AnalysisPage";
import DashboardPage from "@/pages/DashboardPage";
import StrategyPage from "@/pages/StrategyPage";
import UnderwritingPage from "@/pages/UnderwritingPage";
import ApplicationPage from "@/pages/ApplicationPage";

export default function App() {
  return (
    <BrowserRouter>
      <AppShell>
        <Routes>
          <Route path="/" element={<AnalysisPage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/strategies" element={<StrategyPage />} />
          <Route path="/underwriting" element={<UnderwritingPage />} />
          <Route path="/apply" element={<ApplicationPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AppShell>
    </BrowserRouter>
  );
}
