import { Printer } from "lucide-react";
import { useParams } from "react-router-dom";

import {
  Alert, api, Button, Card, DetailList, ErrorState, formatDate, money, PageHeader, quantity, Skeleton, StatusBadge, toast, unwrap, useCan, useCompany, useMutation, useQuery, useTranslation,
} from "@/sdk";

import { printHtml } from "../lib/print";
import type { PayslipDoc } from "../lib/types";

const DETAIL_KEYS = ["basic_pay_full", "days_worked", "days_in_period", "unpaid_leave_days", "overtime_hours", "hours_worked"] as const;

/** A payslip as it prints (header, who, earnings, benefits, deductions, totals), plus a print button. */
export default function PayslipPage() {
  const { t } = useTranslation("people");
  const { payslipId = "" } = useParams();
  const canRuns = useCan("payroll.view");
  const { companies } = useCompany();
  const path = { params: { path: { payslip_id: payslipId } } };
  const slip = useQuery({ queryKey: ["people", "payslip", payslipId], queryFn: () => unwrap(api.GET("/api/v1/people/payslips/{payslip_id}", path)) });
  const doc = useQuery({ queryKey: ["people", "payslip-doc", payslipId], queryFn: async () => (await unwrap(api.GET("/api/v1/people/payslips/{payslip_id}/print", path))) as PayslipDoc });
  const run = useQuery({
    enabled: !!slip.data && canRuns, retry: false, queryKey: ["people", "run", slip.data?.run_id],
    queryFn: () => unwrap(api.GET("/api/v1/people/payroll-runs/{run_id}", { params: { path: { run_id: slip.data!.run_id } } })),
  });
  const currency = companies.find((c) => c.id === run.data?.company_id)?.currency ?? (companies.length === 1 ? companies[0]?.currency : undefined);

  const print = useMutation({
    meta: { silent: true },
    mutationFn: async (copy: boolean) => unwrap(api.GET("/api/v1/people/payslips/{payslip_id}/print", { params: { path: { payslip_id: payslipId }, query: { format: "html", copy } }, parseAs: "text" })),
    onSuccess: (html) => printHtml(String(html)),
    onError: (e) => toast((e as Error).message, "bad"),
  });

  if (slip.error) return <ErrorState title={t("payslip.notFound")} message={slip.error.message} onRetry={() => void slip.refetch()} />;
  const s = slip.data;
  if (!s) return <Skeleton className="h-64 w-full" />;
  const d = doc.data;
  const section = (title: string, lines: { label: string; amount: string | number }[]) => lines.length > 0 && (
    <section className="py-3">
      <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">{title}</h3>
      <dl className="space-y-1">{lines.map((l, i) => <div key={i} className="flex justify-between gap-4 text-sm"><dt>{l.label}</dt><dd className="tnum">{money(l.amount, currency)}</dd></div>)}</dl>
    </section>
  );
  const detail = s.detail as Record<string, unknown>;
  const facts = DETAIL_KEYS.filter((k) => detail[k] !== undefined).map((k) => ({ label: t(`payslip.detail.${k}`), value: k === "basic_pay_full" ? money(String(detail[k]), currency) : quantity(String(detail[k])) }));

  return (
    <>
      <PageHeader back={{ to: canRuns ? `/payroll/${s.run_id}` : "/employees", label: canRuns ? t("run.back") : t("employees.back") }} title={s.full_name}
        description={<span className="flex flex-wrap items-center gap-2"><span className="font-mono">{s.employee_no}</span><span>{formatDate(s.period_start)} → {formatDate(s.period_end)}</span><StatusBadge status={s.status} /></span>}
        actions={<>
          <Button variant="secondary" loading={print.isPending && print.variables === true} onClick={() => print.mutate(true)}>{t("payslip.printCopy")}</Button>
          <Button loading={print.isPending && print.variables === false} onClick={() => print.mutate(false)}><Printer className="h-4 w-4" />{t("payslip.print")}</Button>
        </>} />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <Card>
          {doc.error ? <ErrorState message={doc.error.message} onRetry={() => void doc.refetch()} /> : !d ? <Skeleton className="h-64" /> : (
            <div className="mx-auto max-w-xl divide-y divide-line">
              <header className="pb-3 text-center">
                {d.header.map((line, i) => <p key={i} className={i === 0 ? "text-base font-semibold" : "text-xs text-muted"}>{line}</p>)}
                <p className="mt-2 text-sm font-semibold uppercase tracking-wide">{d.title}{d.is_copy ? ` · ${t("payslip.copy")}` : ""}</p>
                <p className="text-xs text-muted">{d.period}</p>
              </header>
              <section className="py-3"><DetailList items={d.employee.map(([label, value]) => ({ label: label ?? "", value }))} /></section>
              {section(t("payslip.earnings"), d.earnings)}
              {section(t("payslip.benefitsInKind"), d.benefits)}
              {section(t("payslip.deductionsList"), d.deductions)}
              <section className="space-y-1 pt-3">
                {d.totals.map((l, i) => <div key={i} className={`flex justify-between gap-4 text-sm ${i === d.totals.length - 1 ? "text-base font-semibold" : ""}`}><span>{l.label}</span><span className="tnum">{money(l.amount, currency)}</span></div>)}
              </section>
              {d.notes.length > 0 && <section className="pt-3">{d.notes.map((n, i) => <Alert key={i} tone="warn">{n}</Alert>)}</section>}
            </div>
          )}
        </Card>
        <div className="space-y-4">
          <Card title={t("payslip.summary")}>
            <DetailList items={[
              { label: t("payslip.gross"), value: money(s.gross_pay, currency) },
              { label: t("payslip.taxable"), value: money(s.taxable_pay, currency) },
              { label: t("payslip.deductions"), value: money(s.total_deductions, currency) },
              { label: t("payslip.net"), value: <span className="font-semibold">{money(s.net_pay, currency)}</span> },
              { label: t("payslip.employerCost"), value: money(s.employer_cost, currency) },
              { label: t("payslip.payMethod"), value: s.pay_method ? t(`bank.methods.${s.pay_method}`, s.pay_method) : null },
            ]} />
          </Card>
          {facts.length > 0 && <Card title={t("payslip.workings")}><DetailList items={facts} /></Card>}
        </div>
      </div>
    </>
  );
}
