import { useState } from "react";

import { api, DataTable, Field, Input, unwrap, useQuery, useTranslation } from "@/sdk";

const iso = (d: Date): string => d.toISOString().slice(0, 10);

/** Hours booked (really worked) against hours billed, per technician, over a period. Not everyone sees everyone: see the docs. */
export function Technicians({ companyId }: { companyId: string }) {
  const { t } = useTranslation("jobs");
  const [from, setFrom] = useState(() => { const d = new Date(); d.setDate(d.getDate() - 29); return iso(d); });
  const [to, setTo] = useState(() => iso(new Date()));
  const report = useQuery({
    queryKey: ["jobs", "technicians", companyId, from, to], enabled: !!companyId && !!from && !!to && from <= to,
    queryFn: () => unwrap(api.GET("/api/v1/jobs/reports/technicians", { params: { query: { company_id: companyId, date_from: from, date_to: to } } })),
  });
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <Field label={t("garage.technicians.from")}><Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
        <Field label={t("garage.technicians.to")}><Input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
      </div>
      <DataTable rows={report.data} loading={report.isLoading} error={report.error?.message} onRetry={() => void report.refetch()}
        rowKey={(r) => r.user_id ?? "none"} empty={{ title: t("garage.technicians.empty"), hint: t("garage.technicians.emptyHint") }}
        columns={[
          { header: t("garage.technicians.name"), cell: (r) => <span className="font-medium">{r.name ?? t("garage.technicians.nobody")}</span> },
          { header: t("garage.technicians.billed"), align: "right", cell: (r) => <span className="tnum">{Number(r.billed_hours).toFixed(2)}</span> },
          { header: t("garage.technicians.booked"), align: "right", cell: (r) => <span className="tnum">{Number(r.booked_hours).toFixed(2)}</span> },
          { header: t("garage.technicians.ratio"), align: "right", hideBelow: "sm", cell: (r) => (Number(r.booked_hours) > 0 ? <span className="tnum">{Math.round((Number(r.billed_hours) / Number(r.booked_hours)) * 100)}%</span> : "—") },
          { header: t("garage.technicians.unbooked"), align: "right", hideBelow: "md", cell: (r) => <span className="tnum">{r.lines_without_booked}</span> },
          { header: t("garage.technicians.open"), align: "right", hideBelow: "md", cell: (r) => <span className="tnum">{r.jobs_open}</span> },
        ]} />
      <p className="text-xs text-muted">{t("garage.technicians.hint")}</p>
    </div>
  );
}
