import { Card, money, type Schemas, Stat, useTranslation } from "@/sdk";

type Dashboard = Schemas["DashboardOut"];

/** The headline figures: recurring revenue per currency (never added across currencies), then people and money owed. */
export function Kpis({ d }: { d: Dashboard }) {
  const { t } = useTranslation("operator");
  const active = d.by_status.active ?? 0;
  const owed = d.past_due;
  return (
    <section aria-label={t("dash.kpis")}>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {d.mrr.length === 0 ? (
          <div className="sm:col-span-2 xl:col-span-2"><Card><p className="text-sm text-muted">{t("dash.noRevenue")}</p></Card></div>
        ) : d.mrr.map((m) => (
          <Stat key={m.currency} label={t("dash.mrrIn", { currency: m.currency })} value={money(m.mrr, m.currency)}
            hint={t("dash.arrHint", { arr: money(m.arr, m.currency), count: m.subscribers })} />
        ))}
        <Stat label={t("dash.activeSubscribers")} value={active} hint={t("dash.activeHint", { total: Object.values(d.by_status).reduce((a, b) => a + b, 0) })} to="/operator/subscribers?status=active" />
        <Stat label={t("dash.trials")} value={d.trials.in_progress} hint={t("dash.trialsHint", { count: d.trials.ending_soon })} to="/operator/subscribers?status=trialing" />
        <Stat label={t("dash.pastDueAmount")} value={owed.length === 0 ? "-" : owed.map((o) => money(o.owed, o.currency)).join(" · ")} tone={owed.length ? "bad" : "ok"}
          hint={owed.length ? t("dash.pastDueInvoices", { count: owed.reduce((n, o) => n + o.invoices, 0) }) : t("dash.nothingOwed")} to="/operator/billing/invoices?status=issued" />
        <Stat label={t("dash.churned")} value={d.churned} tone={d.churned > 0 ? "bad" : undefined} hint={t("dash.inPeriod", { days: d.period_days })} to="/operator/subscribers?flag=churned" />
        <Stat label={t("dash.newSubscribers")} value={d.new_subscribers} hint={t("dash.inPeriod", { days: d.period_days })} to="/operator/subscribers" />
      </div>
      <p className="mt-1 text-xs text-muted">{t("dash.perCurrency")}</p>
    </section>
  );
}
