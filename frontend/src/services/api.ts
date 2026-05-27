import axios from "axios";

const api = axios.create({
  baseURL: "/api/v1",
  timeout: 120000,
});

export interface AnalysisRequest {
  query: string;
  session_id?: string;
}

export interface ExecutionLog {
  agent: string;
  step: number;
  action: string;
  result: string;
  latency_ms: number;
}

export interface AnalysisResponse {
  session_id: string;
  query: string;
  intent: string;
  report: string;
  execution_log: ExecutionLog[];
  total_latency_ms: number;
}

export interface HealthResponse {
  status: string;
  mysql: boolean;
  redis: boolean;
  milvus?: boolean;
  langsmith_tracing?: boolean;
  langsmith_node_tracing?: boolean;
}

export interface Strategy {
  strategy_id: string;
  name: string;
  description: string;
  status: string;
  created_by: string;
  approved_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface Report {
  report_id: string;
  session_id: string;
  title: string;
  query_text: string;
  summary?: string;
  created_at: string;
}

export interface MetricsSummary {
  total_loans: number;
  total_users: number;
  total_loan_amount: number;
  total_outstanding: number;
  avg_interest_rate: number;
  overdue_rate_pct: number;
  bad_rate_pct: number;
}

export interface StatsResponse {
  summary: MetricsSummary;
  status_distribution: Record<string, number>;
  grade_distribution: Array<{
    grade: string;
    cnt: number;
    avg_rate: number;
    overdue_rate_pct: number;
  }>;
  table_counts: Record<string, number>;
  _cache: string;
}

export const analyzeQuery = (data: AnalysisRequest) =>
  api.post<AnalysisResponse>("/analyze", data);

export const getHealth = () => api.get<HealthResponse>("/health");

export const getStats = () => api.get<StatsResponse>("/stats");

export const getStrategies = (status?: string) =>
  api.get<{ strategies: Strategy[] }>("/strategies", {
    params: status ? { status } : {},
  });

export const updateStrategy = (id: string, status: string) =>
  api.patch<{ strategy_id: string; new_status: string }>(
    `/strategies/${id}`,
    { status, approved_by: "admin" }
  );

export const deleteStrategy = (id: string) =>
  api.delete<{ deleted: string }>(`/strategies/${id}`);

export const getReports = (limit = 20) =>
  api.get<{ reports: Report[] }>("/reports", { params: { limit } });

// ── Session management ─────────────────────────────────────────
export interface SessionSummary {
  session_id: string;
  preview: string;
  last_active: string;
  message_count: number;
}

export interface SessionMessage {
  role: "user" | "assistant";
  content: string;
  intent: string;
  ts: string;
}

export const getSessions = () =>
  api.get<{ sessions: SessionSummary[] }>("/sessions");

export const getSessionMessages = (sessionId: string) =>
  api.get<{ session_id: string; messages: SessionMessage[] }>(
    `/sessions/${sessionId}/messages`
  );

export const deleteSession = (sessionId: string) =>
  api.delete<{ session_id: string; deleted_file: boolean; deleted_reports: number }>(
    `/sessions/${sessionId}`
  );

// ── Underwriting ──────────────────────────────────────────────
export interface Applicant {
  applicant_id: string;
  approval_report?: string;
  score_breakdown?: ScoreBreakdown;
  name: string;
  annual_income: number;
  emp_title?: string;
  emp_length?: string;
  home_ownership?: string;
  province?: string;
  city?: string;
  dti?: number;
  fico_score?: number;
  delinq_2yrs?: number;
  inq_last_6mths?: number;
  revol_util?: number;
  open_acc?: number;
  total_acc?: number;
  pub_rec?: number;
  requested_amount: number;
  requested_term: number;
  product_type: string;
  channel?: string;
  purpose?: string;
  status: string;
  approved_amount?: number;
  approved_rate?: number;
  risk_score?: number;
  risk_grade?: string;
  decision_reason?: string;
  reviewed_at?: string;
  created_at: string;
}

export interface ScoreBreakdown {
  fico: number;
  dti: number;
  delinq: number;
  emp_length: number;
  home: number;
  revol_util: number;
  inquiries: number;
  total?: number;
}

export interface ApproveResponse {
  applicant_id: string;
  task_id: string;
  status: string;
}

export interface ApproveStatusResponse {
  applicant_id: string;
  task_id: string;
  status: string;
  applicant_status?: string;
  decision?: string;
  risk_score?: number;
  risk_grade?: string;
  suggested_amount?: number;
  suggested_rate?: number;
  score_breakdown?: ScoreBreakdown;
  decision_reasons?: string[];
  risk_warnings?: string[];
  compliance_check?: Record<string, { passed: boolean; rule: string }>;
  execution_log?: ExecutionLog[];
  total_latency_ms?: number;
  error_detail?: string;
  approval_report?: string;
}

export const generateApplicants = (count = 20, fico_profile = "random") =>
  api.post<{ count: number; applicant_ids: string[] }>(`/applicants/generate`, null, {
    params: { count, fico_profile },
  });

export const listApplicants = (status?: string, limit = 50) =>
  api.get<{ applicants: Applicant[] }>("/applicants", {
    params: { ...(status ? { status } : {}), limit },
  });

export const getApplicant = (id: string) =>
  api.get<Applicant>(`/applicants/${id}`);

export const approveApplicant = (id: string, sessionId?: string) =>
  api.post<ApproveResponse>(`/applicants/${id}/approve`, {
    session_id: sessionId ?? null,
  });

export const getApproveStatus = (id: string, taskId: string) =>
  api.get<ApproveStatusResponse>(`/applicants/${id}/approve-status`, {
    params: { task_id: taskId },
  });

export const resetApplicant = (id: string) =>
  api.post<{ applicant_id: string; status: string; message: string }>(
    `/applicants/${id}/reset`
  );

export interface BatchApproveTask {
  applicant_id: string;
  task_id: string;
}

export const batchApprove = (applicantIds?: string[], limit = 50) =>
  api.post<{ count: number; tasks: BatchApproveTask[] }>(
    `/applicants/batch-approve`,
    applicantIds?.length ? { applicant_ids: applicantIds } : { limit }
  );

export const deleteApplicant = (id: string) =>
  api.delete<{ applicant_id: string; deleted: boolean }>(`/applicants/${id}`);

export const deleteApplicantsBatch = (status?: string) =>
  api.delete<{ deleted: number; status_filter: string }>(`/applicants`, {
    params: status ? { status } : {},
  });

export interface FormOptions {
  product_types: string[];
  channels: string[];
  purposes: string[];
  emp_titles: string[];
  emp_lengths: string[];
  home_ownerships: string[];
  terms: number[];
  locations: Record<string, string[]>;
}

export interface ApplicantSubmitRequest {
  name: string;
  annual_income: number;
  dti: number;
  fico_score: number;
  emp_title: string;
  emp_length: string;
  home_ownership: string;
  province: string;
  city: string;
  delinq_2yrs: number;
  inq_last_6mths: number;
  revol_util: number;
  open_acc: number;
  total_acc: number;
  pub_rec: number;
  requested_amount: number;
  requested_term: number;
  product_type: string;
  channel: string;
  purpose: string;
  auto_start?: boolean;
}

export interface ApplicantSubmitResponse {
  applicant_id: string;
  task_id: string | null;
  status: string;
  message: string;
}

export const getFormOptions = () =>
  api.get<FormOptions>("/applicants/form-options");

export const submitApplication = (data: ApplicantSubmitRequest) =>
  api.post<ApplicantSubmitResponse>("/applicants/submit", {
    ...data,
    auto_start: data.auto_start ?? true,
  });

export default api;
