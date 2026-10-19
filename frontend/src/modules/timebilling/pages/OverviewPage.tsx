import { Link } from "react-router-dom";
import { useState } from "react";

import { api, Badge, Card, DataTable, Field, Input, money, PageHeader, percent, Stat, today, unwrap, useCan, useQuery, useTranslation } from "@/sdk";

import { CompanyPicker } from "../components/CompanyBar";
import { GetStarted } from "../components/GetStarted";
import { useWorkCompany } from "../hooks";
import { addDays, barWidth, formatDuration } from "../lib";

/** How busy and how billable each person was over a period (the manager's view). */
export default function OverviewPage() {
  const { t } = useTranslation("timebilling");
  const { companyId, companies, setCompanyId, currency } = useWorkCompany();
  const canBill = useCan("time.bill");
  const [from, setFrom] = useState(() => addDays(today(), -27));
  const [to, setTo] = useState(() => today());
  const valid = !!from && !!to && from <= to;
  const rows = useQuery({
    queryKey: ["timebilling", "utilisation", companyId, from, to], enabled: !!companyId && valid,
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/reports/utilisation", { params: { query: { company_id: companyId, date_from: from, date_to: to } } })),
  });
  const owner = useQuery({
    queryKey: ["timebilling", "owner", companyId, from, to], enabled: !!companyId && valid,
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/reports/owner", { params: { query: { company_id: companyId, date_from: from, date_to: to } } })),
  });
  const o = owner.data;
  const logged = rows.data?.reduce((s, r) => s + r.logged_minutes, 0) ?? 0;
  const billable = rows.data?.reduce((s, r) => s + r.billable_minutes, 0) ?? 0;
  const capacity = rows.data?.reduce((s, r) => s + r.capacity_minutes, 0) ?? 0;

  return (
    <>
      <PageHeader title={t("overview.title")} description={t("overview.hint")} actions={<CompanyPicker companies={companies} value={companyId} onChange={setCompanyId} />} />
      <GetStarted companyId={companyId} />
      <Card className="mb-4">
        <div className="flex flex-wrap items-end gap-4">
          <Field label={t("from")}><Input type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} /></Field>
          <Field label={t("to")} error={!valid && from && to ? t("overview.badRange") : null}><Input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} /></Field>
        </div>
      </Card>
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <Stat label={t("overview.logged")} value={formatDuration(logged)} loading={rows.isLoading} />
        <Stat label={t("overview.billable")} value={formatDuration(billable)} hint={logged ? t("overview.ofLogged", { percent: percent((billable * 100) / logged, 0) }) : undefined} loading={rows.isLoading} />
        <Stat label={t("overview.capacity")} value={formatDuration(capacity)} hint={capacity ? t("overview.usedOf", { percent: percent((billable * 100) / capacity, 0) }) : undefined} loading={rows.isLoading} />
      </div>
      {o && (
        <div className="mb-4 space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label={t("owner.wip")} value={money(o.wip_total, currency)} hint={t("owner.wipHint")} />
            <Stat label={t("owner.realisation")} value={o.realisation.percent === null ? "—" : percent(o.realisation.percent, 0)} hint={t("owner.realisationHint", { down: money(o.realisation.written_down, currency), off: money(o.realisation.written_off, currency) })} />
            <Stat label={t("owner.utilisation")} value={o.utilisation_percent === null ? "—" : percent(o.utilisation_percent, 0)} hint={t("owner.utilisationHint")} />
            <Stat label={t("owner.waiting")} value={String(o.weeks_waiting + o.reviews_waiting + o.tasks_overdue)} hint={t("owner.waitingHint", { weeks: o.weeks_waiting, invoices: o.reviews_waiting, late: o.tasks_overdue })} tone={o.tasks_overdue > 0 ? "bad" : undefined} />
          </div>
          <Card title={t("owner.ageing")}>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {o.wip_buckets.map((b, i) => (
                <div key={b.label}><p className="text-xs text-muted">{t(`unbilled.age.${["d30", "d60", "d90", "older"][i]}`)}</p><p className={`tnum text-lg font-semibold ${i === 3 && Number(b.amount) > 0 ? "text-bad" : ""}`}>{money(b.amount, currency)}</p></div>
              ))}
            </div>
            {canBill && <Link className="mt-3 inline-block text-sm font-medium text-brand-strong hover:underline" to="/time/unbilled">{t("owner.openUnbilled")}</Link>}
          </Card>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title={t("owner.atRisk")} flush>
              {o.at_risk.length === 0 ? <p className="px-4 py-6 text-sm text-muted">{t("owner.atRiskNone")}</p> : (
                <ul className="divide-y divide-line text-sm">
                  {o.at_risk.map((r) => (
                    <li key={r.project_id} className="flex items-center justify-between gap-3 px-4 py-2.5">
                      <Link className="min-w-0 hover:underline" to={`/projects/${r.project_id}`}><span className="block truncate font-medium">{r.code} · {r.name}</span><span className="block truncate text-xs text-muted">{r.client_name} · {t(`owner.reason.${r.reason}`)}</span></Link>
                      <Badge tone={r.state === "over" ? "bad" : "warn"}>{percent(r.percent, 0)}</Badge>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card title={t("owner.retainers")} flush>
              {o.retainers.length === 0 ? <p className="px-4 py-6 text-sm text-muted">{t("owner.retainersNone")}</p> : (
                <ul className="divide-y divide-line text-sm">
                  {o.retainers.map((r) => (
                    <li key={r.id} className="flex items-center justify-between gap-3 px-4 py-2.5">
                      <Link className="min-w-0 hover:underline" to={`/projects/${r.project_id}`}><span className="block truncate font-medium">{r.project_code} · {r.project_name}</span><span className="block text-xs text-muted">{r.expires_on ? t("owner.expires", { date: r.expires_on }) : formatDuration(r.balance_minutes)}</span></Link>
                      <Badge tone={r.used_percent >= 100 ? "bad" : "warn"}>{percent(r.used_percent, 0)}</Badge>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
          {o.realisation.written_down !== "0.00" && <p className="text-xs text-muted">{t("owner.realisationNote")}</p>}
        </div>
      )}
      <h2 className="mb-2 text-sm font-semibold">{t("owner.people")}</h2>
      <DataTable
        rows={rows.data} loading={rows.isLoading} error={rows.error?.message} onRetry={() => void rows.refetch()} rowKey={(r) => r.user_id}
        empty={{ title: t("overview.empty"), hint: t("overview.emptyHint") }}
        columns={[
          { header: t("approvals.person"), sortValue: (r) => r.name, cell: (r) => <span className="font-medium">{r.name}</span> },
          { header: t("overview.logged"), align: "right", hideBelow: "sm", sortValue: (r) => r.logged_minutes, cell: (r) => <span className="tnum">{formatDuration(r.logged_minutes)}</span> },
          { header: t("overview.billable"), align: "right", sortValue: (r) => r.billable_minutes, cell: (r) => <span className="tnum">{formatDuration(r.billable_minutes)}</span> },
          { header: t("overview.capacity"), align: "right", hideBelow: "md", sortValue: (r) => r.capacity_minutes, cell: (r) => <span className="tnum">{formatDuration(r.capacity_minutes)}</span> },
          {
            header: t("overview.used"), sortValue: (r) => Number(r.percent), className: "min-w-[9rem]",
            cell: (r) => (
              <div className="flex items-center gap-2">
                <div className="h-2 w-24 overflow-hidden rounded-full bg-sunken" role="img" aria-label={t("overview.usedAria", { percent: percent(r.percent, 0) })}>
                  <div className="h-full rounded-full bg-brand" style={{ width: `${barWidth(r.percent)}%` }} />
                </div>
                <span className="tnum text-xs font-medium">{r.capacity_minutes > 0 ? percent(r.percent, 0) : "—"}</span>
              </div>
            ),
          },
        ]} />
    </>
  );
}
