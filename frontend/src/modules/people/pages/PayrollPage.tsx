import { Plus } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  api, Button, DataTable, Drawer, Field, formatDate, FormGrid, Input, money, Pager, PageHeader, Select, StatusBadge, toast, today, unwrap, useCan, useFormState, useMutation, usePagedList,
  useQueryClient, useTranslation,
} from "@/sdk";

import { CompanySelect } from "../components/CompanySelect";
import { monthBounds } from "../lib/calendar";
import { useScope } from "../lib/lookups";
import { totalsOf } from "../lib/types";

const STATUSES = ["draft", "calculated", "pending_approval", "approved", "posted", "paid", "cancelled"] as const;

/** Payroll runs: one per period. Start a run, then open it to calculate, review, approve and pay. */
export default function PayrollPage() {
  const { t } = useTranslation("people");
  const canPrepare = useCan("payroll.prepare");
  const scope = useScope();
  const [creating, setCreating] = useState(false);
  const [status, setStatus] = useState("");
  const list = usePagedList(["people", "runs", scope.companyId, status], (limit, offset) =>
    unwrap(api.GET("/api/v1/people/payroll-runs", { params: { query: { company_id: scope.companyId || undefined, status: status || undefined, limit, offset } } })));
  const add = canPrepare ? <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" />{t("run.new")}</Button> : undefined;

  return (
    <>
      <PageHeader title={t("payroll.title")} description={t("payroll.hint")} actions={add} />
      <DataTable
        rows={list.rows} loading={list.query.isLoading || scope.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(r) => r.id}
        rowHref={(r) => `/payroll/${r.id}`}
        toolbar={<>
          <CompanySelect companies={scope.companies} value={scope.companyId} onChange={scope.setCompanyId} />
          <Select aria-label={t("status")} className="w-auto" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("leave.anyStatus")}</option>{STATUSES.map((s) => <option key={s} value={s}>{t(`state.${s}`)}</option>)}
          </Select>
        </>}
        empty={{ title: status ? t("payroll.noMatch") : t("payroll.empty"), hint: status ? undefined : t("payroll.emptyHint"), action: status ? undefined : add }}
        columns={[
          { header: t("period"), sortValue: (r) => r.period_start, cell: (r) => <span className="font-medium">{formatDate(r.period_start)} → {formatDate(r.period_end)}</span> },
          { header: t("run.payDateShort"), hideBelow: "sm", cell: (r) => formatDate(r.pay_date) },
          { header: t("run.employees"), hideBelow: "md", align: "right", cell: (r) => totalsOf(r).employees ?? "—" },
          { header: t("payslip.net"), align: "right", cell: (r) => (totalsOf(r).net_pay ? money(totalsOf(r).net_pay, scope.companies.find((c) => c.id === r.company_id)?.currency) : "—") },
          { header: t("status"), cell: (r) => <StatusBadge status={r.status} /> },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
      {creating && <NewRun onClose={() => setCreating(false)} />}
    </>
  );
}

function NewRun({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation("people");
  const qc = useQueryClient();
  const navigate = useNavigate();
  const scope = useScope();
  const bounds = monthBounds(today().slice(0, 7));
  const f = useFormState({ company_id: "", period_start: bounds.from, period_end: bounds.to, pay_date: bounds.to });
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/people/payroll-runs", { body: { company_id: f.values.company_id || scope.companyId, period_start: f.values.period_start, period_end: f.values.period_end, pay_date: f.values.pay_date } })),
    onSuccess: (run) => { void qc.invalidateQueries({ queryKey: ["people", "runs"] }); toast(t("run.created"), "ok"); onClose(); navigate(`/payroll/${run.id}`); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  return (
    <Drawer open onClose={onClose} title={t("run.new")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="run-form" loading={save.isPending}>{t("run.create")}</Button></>}>
      <form id="run-form" onSubmit={submit} className="space-y-4">
        <p className="rounded-lg bg-info-soft px-3 py-2 text-sm text-info">{t("run.newInfo")}</p>
        {scope.companies.length > 1 && (
          <Field label={t("company")}><Select value={f.values.company_id || scope.companyId} onChange={(e) => f.set("company_id", e.target.value)}>{scope.companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select></Field>
        )}
        <FormGrid>
          <Field label={t("run.periodStart")} required error={f.error("period_start")}><Input type="date" {...f.bind("period_start")} required /></Field>
          <Field label={t("run.periodEnd")} required error={f.error("period_end")}><Input type="date" min={f.values.period_start} {...f.bind("period_end")} required /></Field>
        </FormGrid>
        <Field label={t("run.payDateLabel")} required error={f.error("pay_date")}><Input type="date" min={f.values.period_start} {...f.bind("pay_date")} required /></Field>
      </form>
    </Drawer>
  );
}
