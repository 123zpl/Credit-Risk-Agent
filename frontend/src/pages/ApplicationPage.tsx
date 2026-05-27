import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  ClipboardList,
  Loader2,
  Send,
  XCircle,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import PageHeader from "@/components/PageHeader";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  getApproveStatus,
  getFormOptions,
  submitApplication,
  type ApplicantSubmitRequest,
  type ApproveStatusResponse,
  type FormOptions,
} from "@/services/api";
import { cn } from "@/lib/utils";

const STEPS = ["基本信息", "收入与信用", "职业与居住", "贷款需求"] as const;

const DEFAULT_FORM: ApplicantSubmitRequest = {
  name: "",
  annual_income: 120000,
  dti: 25,
  fico_score: 680,
  emp_title: "软件工程师",
  emp_length: "3年",
  home_ownership: "租房",
  province: "广东省",
  city: "广州市",
  delinq_2yrs: 0,
  inq_last_6mths: 2,
  revol_util: 35,
  open_acc: 8,
  total_acc: 15,
  pub_rec: 0,
  requested_amount: 50000,
  requested_term: 36,
  product_type: "借呗",
  channel: "APP首页",
  purpose: "家庭装修",
};

function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: React.ReactNode;
  hint?: string;
}) {
  return (
    <div className="space-y-1.5">
      <label className="text-sm font-medium">{label}</label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

function DecisionBadge({ decision }: { decision?: string }) {
  const map: Record<string, string> = {
    APPROVED: "bg-emerald-100 text-emerald-700",
    REJECTED: "bg-red-100 text-red-700",
    MANUAL_REVIEW: "bg-amber-100 text-amber-700",
  };
  const label: Record<string, string> = {
    APPROVED: "审批通过",
    REJECTED: "审批拒绝",
    MANUAL_REVIEW: "转人工复核",
  };
  if (!decision) return null;
  return (
    <span className={cn("rounded-full px-3 py-1 text-sm font-medium", map[decision] ?? "bg-muted")}>
      {label[decision] ?? decision}
    </span>
  );
}

export default function ApplicationPage() {
  const [step, setStep] = useState(0);
  const [form, setForm] = useState<ApplicantSubmitRequest>(DEFAULT_FORM);
  const [options, setOptions] = useState<FormOptions | null>(null);
  const [loadingOpts, setLoadingOpts] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [applicantId, setApplicantId] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [status, setStatus] = useState<ApproveStatusResponse | null>(null);
  const [polling, setPolling] = useState(false);

  useEffect(() => {
    getFormOptions()
      .then((res) => setOptions(res.data))
      .catch(() => setError("无法加载表单选项，请刷新重试"))
      .finally(() => setLoadingOpts(false));
  }, []);

  const cities = useMemo(
    () => options?.locations[form.province] ?? [],
    [options, form.province],
  );

  const patch = (partial: Partial<ApplicantSubmitRequest>) =>
    setForm((prev) => ({ ...prev, ...partial }));

  const onProvinceChange = (province: string) => {
    const cityList = options?.locations[province] ?? [];
    patch({ province, city: cityList[0] ?? "" });
  };

  const validateStep = (): string | null => {
    if (step === 0 && !form.name.trim()) return "请填写姓名";
    if (step === 3) {
      if (form.requested_amount < 2000 || form.requested_amount > 200000)
        return "申请金额须在 2,000～200,000 元之间";
    }
    return null;
  };

  const handleNext = () => {
    const msg = validateStep();
    if (msg) {
      setError(msg);
      return;
    }
    setError(null);
    setStep((s) => Math.min(s + 1, STEPS.length - 1));
  };

  const pollStatus = useCallback(async (aid: string, tid: string) => {
    setPolling(true);
    const deadline = Date.now() + 180_000;
    try {
      while (Date.now() < deadline) {
        const res = await getApproveStatus(aid, tid);
        setStatus(res.data);
        const done = ["SUCCESS", "FAILURE"].includes(res.data.status)
          || ["APPROVED", "REJECTED", "MANUAL_REVIEW"].includes(res.data.applicant_status ?? "");
        if (done) return;
        await new Promise((r) => setTimeout(r, 2000));
      }
      setError("审批时间较长，请记下申请编号稍后在「贷前授信」页查看");
    } finally {
      setPolling(false);
    }
  }, []);

  const handleSubmit = async () => {
    const msg = validateStep();
    if (msg) {
      setError(msg);
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const res = await submitApplication(form);
      setApplicantId(res.data.applicant_id);
      setTaskId(res.data.task_id);
      if (res.data.task_id) {
        await pollStatus(res.data.applicant_id, res.data.task_id);
      }
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "提交失败，请稍后重试");
    } finally {
      setSubmitting(false);
    }
  };

  if (loadingOpts) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (applicantId && (polling || status)) {
    const finished = status && (
      status.status === "SUCCESS"
      || ["APPROVED", "REJECTED", "MANUAL_REVIEW"].includes(status.applicant_status ?? "")
    );
    return (
      <div className="mx-auto max-w-2xl space-y-6">
        <PageHeader
          title="贷款申请"
          description="您的申请已提交，Agent 正在完成贷前审批"
        />
        <div className="studio-panel">
          <div className="studio-panel-body space-y-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-sm text-muted-foreground">申请编号</p>
                <p className="font-mono text-sm">{applicantId}</p>
              </div>
              {polling && (
                <Badge variant="secondary" className="gap-1">
                  <Loader2 className="h-3 w-3 animate-spin" /> 审批中
                </Badge>
              )}
              {finished && <DecisionBadge decision={status?.decision ?? status?.applicant_status} />}
            </div>

            {finished && status && (
              <div className="space-y-3 rounded-lg border bg-muted/30 p-4 text-sm">
                {status.risk_score != null && (
                  <p>风险评分：<strong>{status.risk_score}</strong>（{status.risk_grade}）</p>
                )}
                {status.suggested_amount != null && (
                  <p>建议额度：<strong>{status.suggested_amount.toLocaleString()}</strong> 元</p>
                )}
                {status.suggested_rate != null && (
                  <p>建议利率：<strong>{status.suggested_rate}%</strong></p>
                )}
                {status.approval_report && (
                  <div className="prose prose-sm max-w-none dark:prose-invert">
                    <ReactMarkdown>{status.approval_report}</ReactMarkdown>
                  </div>
                )}
              </div>
            )}

            {!finished && !polling && (
              <Alert>
                <AlertDescription>审批仍在进行，请稍后在「贷前授信」页面查看结果。</AlertDescription>
              </Alert>
            )}

            <Button
              variant="outline"
              onClick={() => {
                setApplicantId(null);
                setTaskId(null);
                setStatus(null);
                setStep(0);
                setForm(DEFAULT_FORM);
              }}
            >
              提交新申请
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <PageHeader
        title="在线贷款申请"
        description="填写信息后提交，系统将自动触发 Underwriting Agent 完成贷前审批"
      />

      <div className="flex gap-2">
        {STEPS.map((label, i) => (
          <div
            key={label}
            className={cn(
              "flex-1 rounded-md border px-2 py-2 text-center text-xs font-medium",
              i === step ? "border-primary bg-primary/5 text-primary" : "text-muted-foreground",
              i < step && "border-emerald-200 bg-emerald-50 text-emerald-700",
            )}
          >
            {i < step ? <CheckCircle2 className="mx-auto mb-0.5 h-4 w-4" /> : null}
            {label}
          </div>
        ))}
      </div>

      {error && (
        <Alert variant="destructive">
          <XCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <div className="studio-panel">
        <div className="studio-panel-body space-y-4">
          {step === 0 && (
            <Field label="姓名">
              <Input
                value={form.name}
                onChange={(e) => patch({ name: e.target.value })}
                placeholder="请输入真实姓名"
              />
            </Field>
          )}

          {step === 1 && (
            <>
              <Field label="年收入（元）">
                <Input
                  type="number"
                  value={form.annual_income}
                  onChange={(e) => patch({ annual_income: Number(e.target.value) })}
                />
              </Field>
              <Field label="负债收入比 DTI（%）" hint="总负债占收入比例，一般低于 50% 较优">
                <Input
                  type="number"
                  value={form.dti}
                  onChange={(e) => patch({ dti: Number(e.target.value) })}
                />
              </Field>
              <Field label="FICO 信用分" hint="300～850">
                <Input
                  type="number"
                  value={form.fico_score}
                  onChange={(e) => patch({ fico_score: Number(e.target.value) })}
                />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="近2年逾期次数">
                  <Input type="number" value={form.delinq_2yrs} onChange={(e) => patch({ delinq_2yrs: Number(e.target.value) })} />
                </Field>
                <Field label="近6月征信查询次数">
                  <Input type="number" value={form.inq_last_6mths} onChange={(e) => patch({ inq_last_6mths: Number(e.target.value) })} />
                </Field>
              </div>
              <Field label="信用卡使用率（%）">
                <Input type="number" value={form.revol_util} onChange={(e) => patch({ revol_util: Number(e.target.value) })} />
              </Field>
            </>
          )}

          {step === 2 && options && (
            <>
              <Field label="职业">
                <Select value={form.emp_title} onValueChange={(v) => patch({ emp_title: v })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {options.emp_titles.map((t) => (
                      <SelectItem key={t} value={t}>{t}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="工作年限">
                <Select value={form.emp_length} onValueChange={(v) => patch({ emp_length: v })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {options.emp_lengths.map((t) => (
                      <SelectItem key={t} value={t}>{t}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="房产状况">
                <Select value={form.home_ownership} onValueChange={(v) => patch({ home_ownership: v })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {options.home_ownerships.map((t) => (
                      <SelectItem key={t} value={t}>{t}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="省份">
                  <Select value={form.province} onValueChange={onProvinceChange}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {Object.keys(options.locations).map((p) => (
                        <SelectItem key={p} value={p}>{p}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
                <Field label="城市">
                  <Select value={form.city} onValueChange={(v) => patch({ city: v })}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {cities.map((c) => (
                        <SelectItem key={c} value={c}>{c}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
              </div>
            </>
          )}

          {step === 3 && options && (
            <>
              <Field label="产品类型">
                <Select value={form.product_type} onValueChange={(v) => patch({ product_type: v })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {options.product_types.map((t) => (
                      <SelectItem key={t} value={t}>{t}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="申请金额（元）" hint="个人网贷上限 20 万元">
                <Input
                  type="number"
                  value={form.requested_amount}
                  onChange={(e) => patch({ requested_amount: Number(e.target.value) })}
                />
              </Field>
              <Field label="贷款期限">
                <Select
                  value={String(form.requested_term)}
                  onValueChange={(v) => patch({ requested_term: Number(v) })}
                >
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {options.terms.map((t) => (
                      <SelectItem key={t} value={String(t)}>{t} 个月</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="借款用途">
                <Select value={form.purpose} onValueChange={(v) => patch({ purpose: v })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {options.purposes.map((t) => (
                      <SelectItem key={t} value={t}>{t}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="申请渠道">
                <Select value={form.channel} onValueChange={(v) => patch({ channel: v })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {options.channels.map((t) => (
                      <SelectItem key={t} value={t}>{t}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
            </>
          )}

          <div className="flex justify-between pt-2">
            <Button
              type="button"
              variant="outline"
              disabled={step === 0 || submitting}
              onClick={() => setStep((s) => s - 1)}
            >
              上一步
            </Button>
            {step < STEPS.length - 1 ? (
              <Button type="button" onClick={handleNext}>
                下一步
              </Button>
            ) : (
              <Button type="button" disabled={submitting} onClick={handleSubmit} className="gap-2">
                {submitting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
                提交并申请审批
              </Button>
            )}
          </div>
        </div>
      </div>

      <p className="flex items-center gap-2 text-xs text-muted-foreground">
        <ClipboardList className="h-3.5 w-3.5" />
        提交后系统将自动运行贷前 Agent（相似用户匹配、政策检索、风险评分、合规审查）。
      </p>
    </div>
  );
}
