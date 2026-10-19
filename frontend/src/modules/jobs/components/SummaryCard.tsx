import { useState } from "react";
import { Link } from "react-router-dom";

import { Alert, api, Button, Card, CustomFields, DetailList, Field, formatDate, Input, money, NumberInput, unwrap, useCan, useTranslation } from "@/sdk";
import { invoiceHref } from "@/modules/pos/public";

import { useJobAction, useUnit } from "../hooks";
import { showsCost } from "../lib";
import { jobHref } from "../public";
import type { Job } from "../types";

/** The side card: money so far, the invoice, the warranty, links to related jobs and the business's own fields. */
export function SummaryCard({ job, currency }: { job: Job; currency: string | undefined }) {
  const { t } = useTranslation("jobs");
  const canManage = useCan("jobs.manage");
  const canInvoice = useCan("jobs.invoice");
  const hasPos = useUnit("pos");
  const row = (label: string, value: string, strong?: boolean) => (
    <div className={`flex justify-between ${strong ? "border-t border-line pt-2 font-semibold" : "text-muted"}`}><dt>{label}</dt><dd className="tnum">{value}</dd></div>
  );
  return (
    <div className="space-y-4">
      <Card title={t("summary.title")}>
        <dl className="space-y-1.5 text-sm">
          {row(t("totals.parts"), money(job.totals.parts_total, currency))}
          {row(t("totals.labour"), money(job.totals.labour_total, currency))}
          {Number(job.totals.charges_total) > 0 && row(t("garage.totals.charges"), money(job.totals.charges_total, currency))}
          {row(t("totals.tax"), money(job.totals.tax, currency))}
          {row(t("totals.total"), money(job.totals.total, currency), true)}
          {showsCost(job) && row(t("totals.cost"), money(job.totals.cost, currency))}
        </dl>
        <p className="mt-2 text-xs text-muted">{t("totals.taxIncluded")}</p>
        <div className="mt-3 text-sm">
          {job.invoiced ? (
            hasPos && job.invoice_id ? <Link className="font-medium text-brand-strong hover:underline" to={invoiceHref(job.invoice_id)}>{t("summary.invoice", { number: job.invoice_number ?? "" })}</Link> : <span>{t("summary.invoice", { number: job.invoice_number ?? "" })}</span>
          ) : canInvoice && !job.customer_id && !job.locked && !job.customer_name ? <Alert tone="info">{t("summary.needCustomer")}</Alert> : null}
        </div>
      </Card>
      <Card title={t("summary.warranty")}>
        <Warranty job={job} canEdit={canManage} />
      </Card>
      {(job.rework_of || job.return_visits.length > 0 || job.collected_at) && (
        <Card title={t("summary.related")}>
          <DetailList items={[
            ...(job.collected_at ? [{ label: t("summary.collected"), value: [formatDate(job.collected_at, true), job.collected_by_name].filter(Boolean).join(" · ") }] : []),
            ...(job.rework_of ? [{ label: t("summary.original"), value: <Link className="font-medium text-brand-strong hover:underline" to={jobHref(job.rework_of.id)}>{job.rework_of.number}</Link> }] : []),
            ...(job.return_visits.length > 0 ? [{ label: t("summary.returnVisits"), value: (
              <span className="flex flex-wrap gap-x-3">{job.return_visits.map((v) => <Link key={v.id} className="font-medium text-brand-strong hover:underline" to={jobHref(v.id)}>{v.number}{v.in_warranty === false ? ` (${t("summary.afterWarranty")})` : ""}</Link>)}</span>
            ) }] : []),
          ]} />
        </Card>
      )}
      <CustomFields entityType="jobs.work_order" entityId={job.id} canEdit={canManage} />
    </div>
  );
}

/** The warranty in days. It can be changed even when the job is locked, and it ends from the day the item was collected. */
function Warranty({ job, canEdit }: { job: Job; canEdit: boolean }) {
  const { t } = useTranslation("jobs");
  const [days, setDays] = useState(String(job.warranty_days));
  const save = useJobAction(job.id, () => unwrap(api.PATCH("/api/v1/jobs/jobs/{job_id}", { params: { path: { job_id: job.id } }, body: { warranty_days: Number(days) } })), { done: t("summary.warrantySaved") });
  const changed = days !== "" && Number(days) !== job.warranty_days;
  return (
    <div className="space-y-3">
      {canEdit ? (
        <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (changed) save.mutate(); }}>
          <Field label={t("summary.warrantyDays")} className="flex-1"><NumberInput value={days} onChange={(v) => setDays(v.replace(/\./g, ""))} /></Field>
          <Button type="submit" variant="secondary" loading={save.isPending} disabled={!changed}>{t("common.save")}</Button>
        </form>
      ) : <Input readOnly aria-label={t("summary.warrantyDays")} value={t("summary.days", { n: job.warranty_days })} />}
      <p className="text-sm text-muted">{job.warranty_ends ? t("summary.warrantyEnds", { date: formatDate(job.warranty_ends) }) : t("summary.warrantyStarts")}</p>
    </div>
  );
}
