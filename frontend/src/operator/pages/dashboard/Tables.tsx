import { Link } from "react-router-dom";

import { type Column, DataTable, formatDate, humanise, money, type Schemas, useTranslation } from "@/sdk";

import { SubscriptionBadge } from "../../components/bits";
import { useDashboardQueries } from "./queries";

type Hot = Schemas["HotSpot"];
type Renewal = Schemas["RenewalRow"];
type Failed = Schemas["FailedJobsRow"];
type Row = Schemas["SubscriberRow"];

const sub = (code: string) => `/operator/subscribers/${encodeURIComponent(code)}`;
const nameLink = (code: string, name: string) => <Link className="font-medium hover:underline" to={sub(code)}>{name}</Link>;

/** Who renews or has a trial ending soon (with links), plus the businesses near a limit and the ones with failed jobs. */
export function Tables({ d }: { d: Schemas["DashboardOut"] }) {
  const { t } = useTranslation("operator");
  const { trials } = useDashboardQueries();

  const renewals: Column<Renewal>[] = [
    { header: t("dash.subscriber"), cell: (r) => nameLink(r.code, r.name) },
    { header: t("dash.plan"), hideBelow: "sm", cell: (r) => <span className="text-sm">{r.plan}</span> },
    { header: t("dash.renews"), cell: (r) => <span className="text-sm">{formatDate(r.period_end)}</span>, sortValue: (r) => r.period_end },
    { header: t("dash.amount"), align: "right", cell: (r) => <span className="text-sm">{money(r.amount, r.currency)}</span> },
  ];
  const ending: Column<Row>[] = [
    { header: t("dash.subscriber"), cell: (r) => nameLink(r.code, r.name) },
    { header: t("dash.plan"), hideBelow: "sm", cell: (r) => <span className="text-sm">{r.plan_name ?? "-"}</span> },
    { header: t("dash.trialEnds"), cell: (r) => <span className="text-sm">{r.trial_end ? formatDate(r.trial_end) : "-"}</span>, sortValue: (r) => r.trial_end },
    { header: t("subs.status"), hideBelow: "md", cell: (r) => <SubscriptionBadge status={r.status} /> },
  ];
  const hot: Column<Hot>[] = [
    { header: t("dash.subscriber"), cell: (h) => nameLink(h.code, h.name) },
    { header: t("dash.kind"), cell: (h) => <span className="text-sm">{t(`dash.limitKinds.${h.kind}`, humanise(h.kind))}</span> },
    { header: t("dash.used"), align: "right", cell: (h) => <span className="tnum text-sm">{h.used} / {h.limit}</span> },
  ];
  const failed: Column<Failed>[] = [
    { header: t("dash.subscriber"), cell: (f) => nameLink(f.code, f.name) },
    { header: t("dash.failedJobs"), align: "right", cell: (f) => <span className="tnum text-sm text-bad">{f.failed_jobs}</span> },
  ];
  const heading = (key: string, link?: { to: string; text: string }) => (
    <div className="mb-2 flex items-baseline justify-between gap-2">
      <h2 className="text-base font-semibold">{t(key)}</h2>
      {link && <Link to={link.to} className="text-xs font-medium text-brand-strong hover:underline">{link.text}</Link>}
    </div>
  );
  return (
    <>
      <div className="grid gap-4 lg:grid-cols-2">
        <section>
          {heading("dash.renewalsTitle", { to: "/operator/subscribers?status=active", text: t("dash.feeds.allSubscribers") })}
          <DataTable rows={d.upcoming_renewals} columns={renewals} rowKey={(r) => r.code} dense pageSize={6} empty={{ title: t("dash.noRenewals"), hint: t("dash.noRenewalsHint") }} />
        </section>
        <section>
          {heading("dash.trialsEnding", { to: "/operator/subscribers?flag=trial_ending", text: t("dash.feeds.allSubscribers") })}
          <DataTable rows={trials.data?.items} columns={ending} rowKey={(r) => r.code} dense pageSize={6} loading={trials.isPending}
            error={trials.isError ? trials.error.message : null} onRetry={() => void trials.refetch()} empty={{ title: t("dash.noTrialsEnding"), hint: t("dash.noTrialsEndingHint") }} />
        </section>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <section>
          {heading("dash.hotSpots")}
          <DataTable rows={d.usage_hot_spots} columns={hot} rowKey={(h) => `${h.code}-${h.kind}`} dense pageSize={6} empty={{ title: t("dash.noHotSpots"), hint: t("dash.noHotSpotsHint") }} />
        </section>
        <section>
          {heading("dash.failedJobsTitle", { to: "/operator/health", text: t("dash.system.open") })}
          <DataTable rows={d.failed_jobs} columns={failed} rowKey={(f) => f.code} dense pageSize={6} empty={{ title: t("dash.noFailedJobs") }} />
        </section>
      </div>
    </>
  );
}
