import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";

import {
  Badge, Button, Card, type Column, DataTable, ErrorState, formatDate, humanise, money, PageHeader, percent, type Schemas, Skeleton, Stat, useTranslation,
} from "@/sdk";

import { BarList } from "../components/bits";
import { opApi, opUnwrap } from "../client";

type Dashboard = Schemas["DashboardOut"];
type Hot = Schemas["HotSpot"];
type Renewal = Schemas["RenewalRow"];
type Failed = Schemas["FailedJobsRow"];

const sub = (code: string) => `/operator/subscribers/${encodeURIComponent(code)}`;

export default function DashboardPage() {
  const { t } = useTranslation("operator");
  const dash = useQuery({ queryKey: ["operator", "dashboard"], queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/dashboard")) });

  const refresh = (
    <Button variant="secondary" size="sm" loading={dash.isFetching && !dash.isPending} onClick={() => void dash.refetch()}>
      <RefreshCw className="h-4 w-4" /> {t("dash.refresh")}
    </Button>
  );

  if (dash.isPending) {
    return (
      <>
        <PageHeader title={t("dash.title")} />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-24 w-full" />)}</div>
      </>
    );
  }
  if (dash.isError) return <><PageHeader title={t("dash.title")} /><ErrorState title={t("dash.loadFailed")} message={dash.error.message} onRetry={() => void dash.refetch()} /></>;
  return <DashboardView d={dash.data} actions={refresh} />;
}

function DashboardView({ d, actions }: { d: Dashboard; actions: React.ReactNode }) {
  const { t } = useTranslation("operator");
  const bars = (counts: Record<string, number>, param: string, label: (key: string) => string) =>
    Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([key, value]) => ({ key, label: label(key), value, to: `/operator/subscribers?${param}=${encodeURIComponent(key)}` }));

  const hot: Column<Hot>[] = [
    { header: t("dash.subscriber"), cell: (h) => <Link className="font-medium hover:underline" to={sub(h.code)}>{h.name}</Link> },
    { header: t("dash.kind"), cell: (h) => <span className="text-sm">{t(`dash.limitKinds.${h.kind}`, humanise(h.kind))}</span> },
    { header: t("dash.used"), align: "right", cell: (h) => <span className="tnum text-sm">{h.used} / {h.limit}</span> },
  ];
  const renewals: Column<Renewal>[] = [
    { header: t("dash.subscriber"), cell: (r) => <Link className="font-medium hover:underline" to={sub(r.code)}>{r.name}</Link> },
    { header: t("dash.plan"), hideBelow: "sm", cell: (r) => <span className="text-sm">{r.plan}</span> },
    { header: t("dash.renews"), cell: (r) => <span className="text-sm">{formatDate(r.period_end)}</span> },
    { header: t("dash.amount"), align: "right", cell: (r) => <span className="text-sm">{money(r.amount, r.currency)}</span> },
  ];
  const failed: Column<Failed>[] = [
    { header: t("dash.subscriber"), cell: (f) => <Link className="font-medium hover:underline" to={sub(f.code)}>{f.name}</Link> },
    { header: t("dash.failedJobs"), align: "right", cell: (f) => <span className="tnum text-sm text-bad">{f.failed_jobs}</span> },
  ];

  return (
    <>
      <PageHeader title={t("dash.title")} description={t("dash.description", { days: d.period_days, time: formatDate(d.generated_at, true) })}
        actions={<><Badge tone="brand" className="py-1">{t("dash.mode", { mode: t(`dash.modes.${d.mode}`, humanise(d.mode)) })}</Badge>{actions}</>} />

      <h2 className="mb-2 text-sm font-semibold text-muted">{t("dash.revenue")}</h2>
      {d.mrr.length === 0 ? (
        <Card><p className="text-sm text-muted">{t("dash.noRevenue")}</p></Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {d.mrr.map((m) => (
            <Stat key={m.currency} label={t("dash.mrrIn", { currency: m.currency })} value={money(m.mrr, m.currency)}
              hint={t("dash.arrHint", { arr: money(m.arr, m.currency), count: m.subscribers })} />
          ))}
        </div>
      )}
      <p className="mt-1 text-xs text-muted">{t("dash.perCurrency")}</p>

      <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label={t("dash.newSubscribers")} value={d.new_subscribers} hint={t("dash.inPeriod", { days: d.period_days })} to="/operator/subscribers" />
        <Stat label={t("dash.churned")} value={d.churned} tone={d.churned > 0 ? "bad" : undefined} hint={t("dash.inPeriod", { days: d.period_days })} to="/operator/subscribers?flag=churned" />
        <Stat label={t("dash.trials")} value={d.trials.in_progress} hint={t("dash.trialsHint", { count: d.trials.ending_soon })} to="/operator/subscribers?flag=trial_ending" />
        <Stat label={t("dash.conversion")} value={d.trials.conversion_percent === null ? "-" : percent(d.trials.conversion_percent)}
          hint={t("dash.conversionHint", { converted: d.trials.converted, lapsed: d.trials.lapsed })} />
        <Stat label={t("dash.pendingRequests")} value={d.pending_requests} tone={d.pending_requests > 0 ? "bad" : undefined} to="/operator/billing/requests" />
        <Stat label={t("dash.draftInvoices")} value={d.draft_invoices} to="/operator/billing/invoices?status=draft" />
        <Stat label={t("dash.unmanaged")} value={d.unmanaged} hint={t("dash.unmanagedHint")} to="/operator/subscribers?flag=unmanaged" />
        <Stat label={t("dash.failedJobsTotal")} value={d.failed_jobs.reduce((n, f) => n + f.failed_jobs, 0)} tone={d.failed_jobs.length > 0 ? "bad" : undefined} />
      </div>

      <Card className="mt-5" title={t("dash.pastDue")} description={t("dash.pastDueHint")}
        actions={<><Link className="text-xs font-medium text-brand-strong hover:underline" to="/operator/billing/invoices?status=issued">{t("dash.openInvoices")}</Link><Link className="text-xs font-medium text-brand-strong hover:underline" to="/operator/subscribers?flag=past_due">{t("dash.pastDueSubscribers")}</Link></>}>
        {d.past_due.length === 0 ? <p className="text-sm text-muted">{t("dash.nothingOwed")}</p> : (
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {d.past_due.map((o) => (
              <li key={o.currency} className="rounded-lg border border-line p-3">
                <p className="tnum text-lg font-semibold text-bad">{money(o.owed, o.currency)}</p>
                <p className="text-xs text-muted">{t("dash.invoicesCount", { count: o.invoices })}</p>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card title={t("dash.byStatus")}><BarList empty={t("dash.noData")} items={bars(d.by_status, "status", (k) => t(`status.${k}`, k))} /></Card>
        <Card title={t("dash.byPlan")}><BarList empty={t("dash.noData")} items={bars(d.by_plan, "plan", (k) => k)} /></Card>
        <Card title={t("dash.byEdition")}><BarList empty={t("dash.noData")} items={bars(d.by_edition, "edition", (k) => k)} /></Card>
        <Card title={t("dash.byCountry")}><BarList empty={t("dash.noData")} items={bars(d.by_country, "country", (k) => k)} /></Card>
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <section>
          <h2 className="mb-2 text-base font-semibold">{t("dash.renewalsTitle")}</h2>
          <DataTable rows={d.upcoming_renewals} columns={renewals} rowKey={(r) => r.code} dense pageSize={8} empty={{ title: t("dash.noRenewals") }} />
        </section>
        <section>
          <h2 className="mb-2 text-base font-semibold">{t("dash.hotSpots")}</h2>
          <DataTable rows={d.usage_hot_spots} columns={hot} rowKey={(h) => `${h.code}-${h.kind}`} dense pageSize={8} empty={{ title: t("dash.noHotSpots"), hint: t("dash.noHotSpotsHint") }} />
        </section>
      </div>
      {d.failed_jobs.length > 0 && (
        <section className="mt-5">
          <h2 className="mb-2 text-base font-semibold">{t("dash.failedJobsTitle")}</h2>
          <DataTable rows={d.failed_jobs} columns={failed} rowKey={(f) => f.code} dense pageSize={8} empty={{ title: t("dash.noFailedJobs") }} />
        </section>
      )}
    </>
  );
}
