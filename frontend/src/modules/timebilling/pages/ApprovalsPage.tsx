import { useState } from "react";
import { Link } from "react-router-dom";

import { api, Badge, Card, DataTable, formatDate, PageHeader, unwrap, useCan, useQuery, useTranslation } from "@/sdk";

import { CompanyPicker } from "../components/CompanyBar";
import { WeekBadge } from "../components/WeekBadge";
import { WeekReview } from "../components/WeekReview";
import { useWorkCompany } from "../hooks";
import { formatDuration } from "../lib";

const DAY = 86_400_000;

/** Timesheets waiting for approval, and the people who have not sent a week yet. */
export default function ApprovalsPage() {
  const { t } = useTranslation("timebilling");
  const { companyId, companies, setCompanyId, currency } = useWorkCompany();
  const canView = useCan("time.view");
  const canPartner = useCan("time.partner");
  const [open, setOpen] = useState<string | null>(null);
  const waiting = useQuery({
    queryKey: ["timebilling", "weeks", "submitted", companyId], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/weeks", { params: { query: { status: "submitted", company_id: companyId, limit: 200 } } })),
  });
  const reviews = useQuery({
    queryKey: ["timebilling", "reviews", "partner", companyId], enabled: !!companyId && canPartner,
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/invoice-reviews", { params: { query: { company_id: companyId, status: "draft", limit: 100 } } })),
  });
  const missing = useQuery({
    queryKey: ["timebilling", "unsubmitted", companyId], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/reports/unsubmitted", { params: { query: { company_id: companyId } } })),
  });

  return (
    <>
      <PageHeader title={t("approvals.title")} description={t("approvals.hint")} actions={<CompanyPicker companies={companies} value={companyId} onChange={setCompanyId} />} />
      <div className="space-y-6">
        <section aria-labelledby="waiting-h">
          <h2 id="waiting-h" className="mb-2 text-sm font-semibold">{t("approvals.waiting")}</h2>
          <DataTable
            rows={waiting.data} loading={waiting.isLoading} error={waiting.error?.message} onRetry={() => void waiting.refetch()} rowKey={(w) => w.id}
            empty={{ title: t("approvals.noneWaiting"), hint: t("approvals.noneWaitingHint") }}
            columns={[
              { header: t("approvals.person"), sortValue: (w) => w.user_name, cell: (w) => <button className="text-left font-medium hover:underline" onClick={() => setOpen(w.id)}>{w.user_name}</button> },
              { header: t("approvals.week"), sortValue: (w) => w.week_start, cell: (w) => formatDate(w.week_start) },
              { header: t("approvals.hours"), align: "right", sortValue: (w) => w.minutes, cell: (w) => <span className="tnum">{formatDuration(w.minutes)}</span> },
              { header: t("approvals.sent"), hideBelow: "md", cell: (w) => { const days = w.submitted_at ? Math.floor((Date.now() - new Date(w.submitted_at).getTime()) / DAY) : 0; return <span>{formatDate(w.submitted_at)}{days >= 2 && <span className="ml-1 text-xs text-warn">{t("approvals.daysWaiting", { count: days })}</span>}</span>; } },
              { header: t("status"), cell: (w) => <WeekBadge status={w.status} pending={w.approval_pending} /> },
              { header: "", align: "right", cell: (w) => <button className="text-xs font-medium text-brand-strong hover:underline" onClick={() => setOpen(w.id)}>{t("approvals.open")}</button> },
            ]} />
        </section>

        {canPartner && (
          <section aria-labelledby="review-h">
            <h2 id="review-h" className="mb-2 text-sm font-semibold">{t("approvals.invoices")}</h2>
            <DataTable rows={(reviews.data ?? []).filter((r) => r.review_status === "requested")} loading={reviews.isLoading} error={reviews.error?.message} onRetry={() => void reviews.refetch()} rowKey={(r) => r.id}
              rowHref={(r) => `/time/reviews/${r.id}`} empty={{ title: t("approvals.noInvoices") }}
              columns={[
                { header: t("date"), cell: (r) => formatDate(r.created_at) },
                { header: t("reviews.memo"), hideBelow: "sm", cell: (r) => r.memo ?? "—" },
                { header: "", align: "right", cell: () => <span className="text-xs font-medium text-brand-strong">{t("approvals.open")}</span> },
              ]} />
          </section>
        )}

        <section aria-labelledby="missing-h">
          <h2 id="missing-h" className="mb-2 text-sm font-semibold">{t("approvals.notSubmitted")}</h2>
          <p className="mb-2 text-xs text-muted">{t("approvals.notSubmittedHint")}</p>
          <DataTable
            rows={missing.data} loading={missing.isLoading} error={missing.error?.message} onRetry={() => void missing.refetch()} rowKey={(m) => `${m.user_id}-${m.week_start}`}
            empty={{ title: t("approvals.allSent") }}
            columns={[
              { header: t("approvals.person"), sortValue: (m) => m.name, cell: (m) => <span className="font-medium">{m.name}</span> },
              { header: t("approvals.week"), sortValue: (m) => m.week_start, cell: (m) => formatDate(m.week_start) },
              { header: t("approvals.hours"), align: "right", cell: (m) => <span className="tnum">{formatDuration(m.minutes)}</span> },
              { header: "", hideBelow: "sm", cell: () => <Badge tone="warn">{t("week.draft")}</Badge> },
            ]} />
        </section>

        {canView && <Card><p className="text-sm text-muted">{t("approvals.seeOverview")} <Link className="font-medium text-brand-strong hover:underline" to="/time/overview">{t("overview.title")}</Link></p></Card>}
      </div>
      <WeekReview weekId={open} currency={currency} onClose={() => setOpen(null)} />
    </>
  );
}
