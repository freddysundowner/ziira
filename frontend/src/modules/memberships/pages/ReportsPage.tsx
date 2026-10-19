import { useState } from "react";

import {
  api, Alert, Card, DataTable, Field, Input, money, PageHeader, percent, Select, Skeleton, Stat, today, unwrap, useCompany, useCurrency, useQuery, useTranslation, ErrorState,
} from "@/sdk";

import { DownloadButton } from "../download";
import { barWidth, busiest, daysAgo, heatGrid, intensity, monthLabel, parseReport, retentionIntensity, tokenShade, type Report } from "../gymLogic";

const RANGES = ["30", "90", "180", "365"] as const;

function Heat({ report }: { report: Report }) {
  const { t } = useTranslation("memberships");
  const grid = heatGrid(report.attendance);
  const best = busiest(report.attendance);
  const hour = (h: number) => `${String(h).padStart(2, "0")}:00`;
  if (grid.total === 0) return <p className="text-sm text-muted">{t("reports.heatEmpty")}</p>;
  return (
    <div className="space-y-3">
      {best && <p className="text-sm">{t("reports.busiest", { day: t(`weekdaysLong.${best.weekday}`), hour: hour(best.hour), count: best.visits })}</p>}
      <div className="overflow-x-auto">
        <div role="img" aria-label={t("reports.heatLabel", { total: grid.total })} className="grid min-w-[36rem] gap-0.5 text-[11px]" style={{ gridTemplateColumns: `4.5rem repeat(${grid.hours.length}, minmax(0, 1fr))` }}>
          <span />
          {grid.hours.map((h) => <span key={h} className="text-center text-muted">{h}</span>)}
          {grid.rows.map((row, d) => (
            <div key={d} className="contents">
              <span className="pr-2 text-right text-muted">{t(`weekdays.${d}`)}</span>
              {row.map((v, i) => (
                <span key={i} title={t("reports.heatCell", { day: t(`weekdaysLong.${d}`), hour: hour(grid.hours[i] ?? 0), count: v })}
                  className="flex h-7 items-center justify-center rounded-sm border border-line/60 text-ink" style={{ backgroundColor: tokenShade("brand", intensity(v, grid.max)) }}>{v > 0 ? v : ""}</span>
              ))}
            </div>
          ))}
        </div>
      </div>
      <p className="text-xs text-muted">{t("reports.heatLegend")}</p>
      <details className="text-sm">
        <summary className="cursor-pointer text-muted">{t("reports.showTable")}</summary>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead><tr><th scope="col" className="py-1 pr-2">{t("reports.day")}</th>{grid.hours.map((h) => <th key={h} scope="col" className="px-1 text-right">{h}</th>)}</tr></thead>
            <tbody>{grid.rows.map((row, d) => <tr key={d}><th scope="row" className="py-1 pr-2 font-medium">{t(`weekdaysLong.${d}`)}</th>{row.map((v, i) => <td key={i} className="px-1 text-right">{v || ""}</td>)}</tr>)}</tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

function Flow({ report }: { report: Report }) {
  const { t } = useTranslation("memberships");
  const max = Math.max(1, ...report.flow.flatMap((f) => [f.new, f.ended]));
  if (report.flow.length === 0) return <p className="text-sm text-muted">{t("reports.noData")}</p>;
  return (
    <ul className="space-y-3">
      {report.flow.map((f) => (
        <li key={f.month} className="grid grid-cols-[4rem_1fr_3.5rem] items-center gap-2 text-sm">
          <span className="text-muted">{monthLabel(f.month)}</span>
          <span className="space-y-1">
            <span className="flex items-center gap-2"><span className="h-3 rounded-sm bg-ok" style={{ width: `${barWidth(f.new, max)}%` }} aria-hidden="true" /><span className="text-xs">{t("reports.newCount", { count: f.new })}</span></span>
            <span className="flex items-center gap-2"><span className="h-3 rounded-sm bg-bad" style={{ width: `${barWidth(f.ended, max)}%` }} aria-hidden="true" /><span className="text-xs">{t("reports.endedCount", { count: f.ended })}</span></span>
          </span>
          <span className={f.net < 0 ? "text-right font-semibold text-bad" : "text-right font-semibold text-ok"}>{f.net > 0 ? `+${f.net}` : f.net}</span>
        </li>
      ))}
    </ul>
  );
}

function Retention({ report }: { report: Report }) {
  const { t } = useTranslation("memberships");
  if (report.retention.length === 0) return <p className="text-sm text-muted">{t("reports.noData")}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[40rem] text-center text-xs">
        <caption className="sr-only">{t("reports.retentionCaption")}</caption>
        <thead>
          <tr><th scope="col" className="py-1 pr-2 text-left font-medium text-muted">{t("reports.joined")}</th>{Array.from({ length: 12 }, (_, k) => <th key={k} scope="col" className="px-1 font-medium text-muted">{k}</th>)}</tr>
        </thead>
        <tbody>
          {report.retention.map((r) => (
            <tr key={r.month}>
              <th scope="row" className="whitespace-nowrap py-1 pr-2 text-left font-medium">{monthLabel(r.month)} <span className="font-normal text-muted">({r.joined})</span></th>
              {Array.from({ length: 12 }, (_, k) => {
                const v = r.percent[k] ?? null;
                return <td key={k} className="border border-line/60 px-1 py-1.5" style={{ backgroundColor: tokenShade("ok", retentionIntensity(v)) }}>{v === null ? "" : `${v}%`}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-muted">{t("reports.retentionHint")}</p>
    </div>
  );
}

/** The owner's overview: members, income, who is leaving, when the club is busy, who owes. */
export default function ReportsPage() {
  const { t } = useTranslation("memberships");
  const { company } = useCompany();
  const currency = useCurrency(company?.id);
  const [range, setRange] = useState<(typeof RANGES)[number]>("180");
  const [branchId, setBranchId] = useState("");
  const end = today();
  const start = daysAgo(end, Number(range));
  const q = useQuery({
    enabled: !!company, queryKey: ["memberships", "report", company?.id, start, end, branchId],
    queryFn: async () => parseReport(await unwrap(api.GET("/api/v1/memberships/reports/overview", { params: { query: { company_id: company?.id ?? "", start, end, branch_id: branchId || undefined } } }))),
  });
  const r = q.data;
  const branches = company?.branches ?? [];

  return (
    <>
      <PageHeader title={t("reportsMenu")} description={t("reports.hint")}
        actions={company && <DownloadButton fileName="members.csv" request={() => api.GET("/api/v1/memberships/exports/{kind}", { params: { path: { kind: "members" }, query: { company_id: company.id } }, parseAs: "blob" })}>{t("reports.downloadMembers")}</DownloadButton>} />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label={t("reports.period")}>
          <Select value={range} onChange={(e) => setRange(e.target.value as typeof range)}>{RANGES.map((x) => <option key={x} value={x}>{t(`reports.ranges.${x}`)}</option>)}</Select>
        </Field>
        {branches.length > 1 && (
          <Field label={t("branch")}>
            <Select value={branchId} onChange={(e) => setBranchId(e.target.value)}><option value="">{t("reports.allBranches")}</option>{branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</Select>
          </Field>
        )}
        <Field label={t("reports.range")}><Input readOnly value={`${start} → ${end}`} aria-label={t("reports.range")} /></Field>
      </div>
      {q.error && <ErrorState message={q.error.message} onRetry={() => void q.refetch()} />}
      {q.isLoading && <div className="grid grid-cols-2 gap-3 lg:grid-cols-4"><Skeleton className="h-24" /><Skeleton className="h-24" /><Skeleton className="h-24" /><Skeleton className="h-24" /></div>}
      {r && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label={t("reports.active")} value={r.members.active} hint={t("reports.heldHint", { count: r.members.paused + r.members.frozen })} />
            <Stat label={t("reports.income")} value={money(r.mrr, currency)} hint={t("reports.incomeHint")} />
            <Stat label={t("reports.atRisk")} value={`${percent(r.atRiskPercent, 0)}`} tone={r.atRiskPercent >= 15 ? "bad" : undefined} hint={t("reports.atRiskHint", { amount: money(r.atRisk, currency) })} />
            <Stat label={t("reports.owed")} value={money(r.owed.owed, currency)} tone={Number(r.owed.owed) > 0 ? "bad" : undefined} hint={t("reports.owedHint", { count: r.owed.people })} />
            <Stat label={t("reports.newEnded")} value={`${r.flow.reduce((a, f) => a + f.new, 0)} / ${r.flow.reduce((a, f) => a + f.ended, 0)}`} hint={t("reports.newEndedHint")} />
            <Stat label={t("reports.visits")} value={r.visits} hint={t("reports.visitors", { count: r.visitors })} />
            <Stat label={t("reports.holds")} value={r.holds.running} hint={t("reports.holdsHint", { count: r.holds.holds })} />
            <Stat label={t("reports.trials")} value={`${r.trials.converted} / ${r.trials.started}`} hint={t("reports.trialsHint")} />
          </div>
          {r.members.inactive > 0 && <Alert tone="warn">{t("reports.inactive", { count: r.members.inactive })}</Alert>}

          <div className="grid gap-4 lg:grid-cols-2">
            <Card title={t("reports.byPlan")}>
              <DataTable rows={r.byPlan} rowKey={(p) => p.plan} dense empty={{ title: t("reports.noData") }}
                columns={[
                  { header: t("plan"), cell: (p) => <span className="font-medium">{p.plan}</span> },
                  { header: t("tabs.members"), align: "right", cell: (p) => p.members },
                  { header: t("reports.incomeMonth"), align: "right", cell: (p) => money(p.mrr, currency) },
                ]} />
            </Card>
            <Card title={t("reports.flow")} description={t("reports.flowHint")}><Flow report={r} /></Card>
          </div>

          <Card title={t("reports.retention")}><Retention report={r} /></Card>
          <Card title={t("reports.heat")} description={t("reports.heatHint")}><Heat report={r} /></Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card title={t("reports.leaving")}>
              <DataTable rows={r.leaving} rowKey={(l) => l.reason} dense empty={{ title: t("reports.noLeavers") }}
                columns={[
                  { header: t("reports.reason"), cell: (l) => l.reason },
                  { header: t("tabs.members"), align: "right", cell: (l) => l.members },
                ]} />
            </Card>
            <Card title={t("reports.owedAge")}>
              <DataTable rows={[
                { label: t("reports.age.d7"), v: r.owed.d7 }, { label: t("reports.age.d30"), v: r.owed.d30 },
                { label: t("reports.age.d60"), v: r.owed.d60 }, { label: t("reports.age.d60plus"), v: r.owed.d60plus },
              ]} rowKey={(x) => x.label} dense empty={{ title: t("reports.noData") }}
                columns={[{ header: t("reports.late"), cell: (x) => x.label }, { header: t("arrears.owed"), align: "right", cell: (x) => money(x.v, currency) }]} />
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card title={t("reports.trainers")}>
              <DataTable rows={r.trainers} rowKey={(x) => x.trainer} dense empty={{ title: t("reports.noTrainers") }}
                columns={[
                  { header: t("extras.trainer"), cell: (x) => x.trainer },
                  { header: t("extras.sessions"), align: "right", cell: (x) => x.sessions },
                  { header: t("extras.earned"), align: "right", cell: (x) => money(x.earned, currency) },
                ]} />
            </Card>
            {r.classes.length > 0 && (
              <Card title={t("reports.classes")}>
                <DataTable rows={r.classes} rowKey={(x) => x.name} dense empty={{ title: t("reports.noData") }}
                  columns={[
                    { header: t("reports.class"), cell: (x) => x.name },
                    { header: t("reports.sessions"), align: "right", cell: (x) => x.sessions },
                    { header: t("reports.fill"), align: "right", cell: (x) => `${x.fill}%` },
                  ]} />
              </Card>
            )}
          </div>
        </div>
      )}
    </>
  );
}
