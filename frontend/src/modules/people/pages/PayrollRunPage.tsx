import { useState } from "react";
import { useParams } from "react-router-dom";

import { Alert, api, Badge, ErrorState, formatDate, money, PageHeader, Skeleton, Stat, StatusBadge, Tabs, unwrap, useCan, useCompany, useQuery, useTranslation } from "@/sdk";

import { ExceptionsCard } from "../components/ExceptionsCard";
import { PaymentPanel } from "../components/PaymentPanel";
import { PayslipsPanel } from "../components/PayslipsPanel";
import { ReturnsPanel } from "../components/ReturnsPanel";
import { RunActions } from "../components/RunActions";
import { RunStepper } from "../components/RunStepper";
import { totalsOf } from "../lib/types";

/** One payroll run: calculate, review what needs a look, submit, approve (by someone else), pay, and the outputs. */
export default function PayrollRunPage() {
  const { t } = useTranslation("people");
  const { runId = "" } = useParams();
  const canPay = useCan("payroll.pay");
  const { companies } = useCompany();
  const [tab, setTab] = useState("payslips");
  const run = useQuery({ queryKey: ["people", "run", runId], queryFn: () => unwrap(api.GET("/api/v1/people/payroll-runs/{run_id}", { params: { path: { run_id: runId } } })) });
  const r = run.data;

  if (run.error) return <ErrorState title={t("run.notFound")} message={run.error.message} onRetry={() => void run.refetch()} />;
  if (!r) return <Skeleton className="h-40 w-full" />;
  const currency = companies.find((c) => c.id === r.company_id)?.currency;
  const totals = totalsOf(r);
  const calculated = r.status !== "draft";
  const blockers = r.exceptions.filter((e) => e.severity === "blocker").length;
  const tabs = [
    { id: "payslips", label: t("run.payslips") },
    { id: "returns", label: t("returns.title") },
    ...(canPay && ["approved", "posted", "paid"].includes(r.status) ? [{ id: "payment", label: t("payment.title") }] : []),
  ];

  return (
    <>
      <PageHeader back={{ to: "/payroll", label: t("payroll.back") }} title={t("run.heading", { start: formatDate(r.period_start), end: formatDate(r.period_end) })}
        description={<span className="flex flex-wrap items-center gap-2"><StatusBadge status={r.status} /><span>{t("run.payDate", { date: formatDate(r.pay_date) })}</span>{r.journal_entry_id && <Badge tone="ok">{t("run.inBooks")}</Badge>}</span>}
        actions={<RunActions run={r} currency={currency} blockers={blockers} />} />
      {r.status !== "cancelled" && <RunStepper status={r.status} />}
      {r.status === "cancelled" && <Alert tone="warn" className="mb-4">{t("run.cancelledNote")}</Alert>}
      {r.reject_note && r.status === "calculated" && <Alert tone="warn" className="mb-4">{t("run.sentBack", { note: r.reject_note })}</Alert>}
      {r.status === "approved" && <Alert tone="info" className="mb-4">{t("run.notPostedNote")}</Alert>}

      {calculated && (
        <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-5">
          <Stat label={t("run.employees")} value={totals.employees ?? 0} />
          <Stat label={t("payslip.gross")} value={money(totals.gross_cash, currency)} hint={totals.benefits && Number(totals.benefits) > 0 ? t("run.plusBenefits", { amount: money(totals.benefits, currency) }) : undefined} />
          <Stat label={t("payslip.deductions")} value={money(totals.total_deductions, currency)} />
          <Stat label={t("payslip.net")} value={money(totals.net_pay, currency)} tone="ok" />
          <Stat label={t("payslip.employerCost")} value={money(totals.employer_cost, currency)} />
        </div>
      )}
      <div className="mb-5"><ExceptionsCard exceptions={r.exceptions} calculated={calculated} /></div>
      {calculated && (
        <>
          <Tabs tabs={tabs} value={tab} onChange={setTab} />
          {tab === "payslips" && <PayslipsPanel run={r} currency={currency} />}
          {tab === "returns" && <ReturnsPanel run={r} currency={currency} />}
          {tab === "payment" && <PaymentPanel run={r} currency={currency} />}
        </>
      )}
    </>
  );
}
