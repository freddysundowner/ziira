import { Link } from "react-router-dom";

import { Badge, EmptyState, formatDate, money, useTranslation } from "@/sdk";

import { SubscriptionBadge } from "../../components/bits";
import { Section } from "./Section";
import { useDashboardQueries } from "./queries";

const sub = (code: string) => `/operator/subscribers/${encodeURIComponent(code)}`;

/** The newest payments, the newest sign-ups and (for those who may read the trail) the last things operators did. */
export function Feeds() {
  const { t } = useTranslation("operator");
  const { feed, activity, seesTrail } = useDashboardQueries();
  return (
    <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
      <Section query={feed} title={t("dash.feeds.payments")} errorTitle={t("dash.feeds.failed")} skeleton="h-48"
        actions={<Link to="/operator/billing/invoices" className="text-xs font-medium text-brand-strong hover:underline">{t("dash.openInvoices")}</Link>}>
        {(f) => f.payments.length === 0 ? <EmptyState title={t("dash.feeds.noPayments")} hint={t("dash.feeds.noPaymentsHint")} /> : (
          <ul className="divide-y divide-line">
            {f.payments.map((p) => (
              <li key={p.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                <span className="min-w-0">
                  {p.tenant_code ? <Link className="block truncate font-medium hover:underline" to={sub(p.tenant_code)}>{p.tenant_name}</Link> : <span className="block truncate font-medium">{p.invoice_number ?? "-"}</span>}
                  <span className="block truncate text-xs text-muted">{p.invoice_number ?? ""} · {formatDate(p.paid_on)}</span>
                </span>
                <span className="text-right"><span className="tnum block font-medium">{money(p.amount, p.currency)}</span>{p.reversed && <Badge tone="bad">{t("dash.feeds.reversed")}</Badge>}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section query={feed} title={t("dash.feeds.signups")} errorTitle={t("dash.feeds.failed")} skeleton="h-48"
        actions={<Link to="/operator/subscribers" className="text-xs font-medium text-brand-strong hover:underline">{t("dash.feeds.allSubscribers")}</Link>}>
        {(f) => f.signups.length === 0 ? <EmptyState title={t("dash.feeds.noSignups")} hint={t("dash.feeds.noSignupsHint")} /> : (
          <ul className="divide-y divide-line">
            {f.signups.map((s) => (
              <li key={s.code} className="flex items-center justify-between gap-3 py-2 text-sm">
                <span className="min-w-0"><Link className="block truncate font-medium hover:underline" to={sub(s.code)}>{s.name}</Link><span className="block truncate text-xs text-muted">{s.plan_name ?? t("status.unmanaged")} · {formatDate(s.created_at)}</span></span>
                <SubscriptionBadge status={s.status ?? "unmanaged"} />
              </li>
            ))}
          </ul>
        )}
      </Section>

      {seesTrail && (
        <Section query={activity} title={t("dash.feeds.activity")} errorTitle={t("dash.feeds.failed")} skeleton="h-48" className="lg:col-span-2 xl:col-span-1"
          actions={<Link to="/operator/audit" className="text-xs font-medium text-brand-strong hover:underline">{t("dash.feeds.fullTrail")}</Link>}>
          {(a) => a.items.length === 0 ? <EmptyState title={t("audit.empty")} /> : (
            <ul className="divide-y divide-line">
              {a.items.map((l) => (
                <li key={l.id} className="py-2 text-sm">
                  <p><span className="font-medium">{l.operator_name}</span> <span className="text-muted">{t(`audit.actions.${l.action}`, { defaultValue: l.action })}</span></p>
                  <p className="truncate text-xs text-muted">{l.target ? `${l.target} · ` : ""}{formatDate(l.occurred_at, true)}{l.outcome !== "ok" ? ` · ${t(`audit.outcomes.${l.outcome}`, l.outcome)}` : ""}</p>
                </li>
              ))}
            </ul>
          )}
        </Section>
      )}
    </div>
  );
}
