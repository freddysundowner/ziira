import { useState } from "react";

import { Alert, api, Badge, Button, DataTable, Field, formatDate, money, PageHeader, Select, unwrap, useCan, useQuery, useTranslation } from "@/sdk";

import { CompanyPicker } from "../components/CompanyBar";
import { DownloadButton } from "../components/DownloadButton";
import { ReviewsList } from "../components/ReviewsList";
import { useStartReview } from "../components/useStartReview";
import { useWorkCompany } from "../hooks";
import { AGE_BUCKETS, formatDuration } from "../lib";
import type { Unbilled } from "../types";

/** Work done and approved but not yet invoiced, by project, with how old it is; start an invoice review from it. */
export default function UnbilledPage() {
  const { t } = useTranslation("timebilling");
  const canBill = useCan("time.bill");
  const { companyId, companies, setCompanyId, currency } = useWorkCompany();
  const [clientId, setClientId] = useState("");
  const start = useStartReview(companyId);
  const clients = useQuery({
    queryKey: ["timebilling", "clients", companyId], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/clients", { params: { query: { company_id: companyId } } })),
  });
  const list = useQuery({
    queryKey: ["timebilling", "unbilled", companyId, clientId], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/unbilled", { params: { query: { company_id: companyId, client_id: clientId || undefined } } })),
  });
  const rows = list.data;
  const sum = (pick: (r: Unbilled) => string | number) => (rows ?? []).reduce((s, r) => s + Number(pick(r)), 0);
  const unpriced = (rows ?? []).reduce((s, r) => s + r.unpriced_minutes, 0);

  const toolbar = (
    <div className="flex flex-wrap items-end gap-3">
      <Field label={t("client")}>
        <Select className="w-56" value={clientId} onChange={(e) => setClientId(e.target.value)}>
          <option value="">{t("unbilled.allClients")}</option>
          {(clients.data ?? []).map((c) => <option key={c.customer_id} value={c.customer_id}>{c.name}</option>)}
        </Select>
      </Field>
      {canBill && clientId && <Button loading={start.isPending && !start.pending?.projectId} onClick={() => start.start({ clientId })}>{t("unbilled.invoiceClient")}</Button>}
    </div>
  );

  return (
    <>
      <PageHeader title={t("unbilled.title")} description={t("unbilled.hint")}
        actions={<><CompanyPicker companies={companies} value={companyId} onChange={setCompanyId} />
          <DownloadButton fileName="unbilled-work.csv" request={() => api.GET("/api/v1/timebilling/reports/unbilled.csv", { params: { query: { company_id: companyId } }, parseAs: "blob" })}>{t("unbilled.download")}</DownloadButton></>} />
      {unpriced > 0 && (
        <Alert tone="warn" className="mb-4">{t("unbilled.unpriced", { time: formatDuration(unpriced) })}</Alert>
      )}
      <DataTable
        rows={rows} loading={list.isLoading} error={list.error?.message} onRetry={() => void list.refetch()} rowKey={(r) => r.project_id} toolbar={toolbar}
        empty={{ title: t("unbilled.empty"), hint: t("unbilled.emptyHint") }}
        columns={[
          { header: t("client"), sortValue: (r) => r.client_name, cell: (r) => <span className="font-medium">{r.client_name}</span> },
          { header: t("projectField"), sortValue: (r) => r.project_code, cell: (r) => <span><span className="font-mono text-xs">{r.project_code}</span><span className="block max-w-[14rem] truncate text-xs text-muted">{r.project_name}</span>{(Number(r.expense_amount) > 0 || Number(r.milestone_amount) > 0) && <span className="block text-xs text-muted">{t("unbilled.time")} {money(r.time_amount, currency)} · {t("unbilled.expenses")} {money(r.expense_amount, currency)} · {t("unbilled.milestones")} {money(r.milestone_amount, currency)}</span>}</span> },
          { header: t("unbilled.hours"), align: "right", hideBelow: "sm", sortValue: (r) => r.minutes, cell: (r) => <span className="tnum whitespace-nowrap">{formatDuration(r.minutes)}</span> },
          ...AGE_BUCKETS.map((b) => ({
            header: t(`unbilled.age.${b.key}`), align: "right" as const, hideBelow: "md" as const,
            cell: (r: Unbilled) => <span className={`tnum ${Number(r.buckets[b.api] ?? 0) === 0 ? "text-muted" : b.key === "older" ? "font-medium text-bad" : ""}`}>{money(r.buckets[b.api] ?? "0", currency)}</span>,
          })),
          { header: t("unbilled.total"), align: "right", sortValue: (r) => Number(r.amount), cell: (r) => <span className="tnum font-semibold">{money(r.amount, currency)}</span> },
          {
            header: t("status"), hideBelow: "sm",
            cell: (r) => (
              <span className="flex flex-wrap gap-1">
                {r.unpriced_minutes > 0 && <Badge tone="warn">{t("unbilled.noRate")}</Badge>}
                {r.in_review_minutes > 0 && <Badge tone="info">{t("unbilled.inReview")}</Badge>}
                {r.oldest && <span className="whitespace-nowrap text-xs text-muted">{t("unbilled.since", { date: formatDate(r.oldest) })}</span>}
              </span>
            ),
          },
          { header: "", align: "right", cell: (r) => canBill && <Button size="sm" variant="secondary" loading={start.isPending && start.pending?.projectId === r.project_id} onClick={() => start.start({ clientId: r.client_id, projectId: r.project_id })}>{t("unbilled.invoice")}</Button> },
        ]}
        footer={rows && rows.length > 0 ? (
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line bg-sunken px-4 py-2.5 text-sm">
            <span className="font-medium">{t("unbilled.totals")}</span>
            <span className="tnum">{formatDuration(sum((r) => r.minutes))} · <strong>{money(sum((r) => r.amount), currency)}</strong></span>
          </div>
        ) : undefined} />
      {start.dialog}
      <section className="mt-8">
        <h2 className="mb-2 text-sm font-semibold">{t("reviews.title")}</h2>
        <ReviewsList companyId={companyId} clients={clients.data} currency={currency} />
      </section>
    </>
  );
}
