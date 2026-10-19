import { Link } from "react-router-dom";

import { api, Badge, DataTable, formatDate, Select, unwrap, useQuery, useTranslation } from "@/sdk";
import { useState } from "react";

import { assetHref } from "../public";

/** Vehicles and devices whose next service is near or past: who to call. */
export function ServiceDue({ companyId }: { companyId: string }) {
  const { t } = useTranslation("jobs");
  const [within, setWithin] = useState("30");
  const rows = useQuery({
    queryKey: ["jobs", "service-due", companyId, within], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/jobs/service-due", { params: { query: { company_id: companyId, within_days: Number(within) } } })),
  });
  return (
    <div className="space-y-3">
      <Select aria-label={t("garage.due.within")} className="w-auto" value={within} onChange={(e) => setWithin(e.target.value)}>
        {["7", "14", "30", "60", "90"].map((d) => <option key={d} value={d}>{t("garage.due.withinDays", { n: d })}</option>)}
      </Select>
      <DataTable rows={rows.data} loading={rows.isLoading} error={rows.error?.message} onRetry={() => void rows.refetch()}
        rowKey={(r) => r.asset.id} rowHref={(r) => assetHref(r.asset.id)} empty={{ title: t("garage.due.empty"), hint: t("garage.due.emptyHint") }}
        columns={[
          { header: t("garage.due.item"), cell: (r) => <span className="font-medium">{r.asset.label}</span> },
          { header: t("garage.due.customer"), cell: (r) => r.customer_name ?? "—", hideBelow: "sm" },
          { header: t("garage.due.date"), cell: (r) => <span className="inline-flex items-center gap-2">{r.asset.next_service_date ? formatDate(r.asset.next_service_date) : "—"}{r.overdue && <Badge tone="bad">{t("garage.due.overdue")}</Badge>}</span> },
          { header: t("garage.due.reading"), align: "right", hideBelow: "md", cell: (r) => (r.asset.next_service_odometer ? <span className="tnum">{Number(r.asset.next_service_odometer)}</span> : "—") },
          { header: "", cell: (r) => <Link className="text-sm font-medium text-brand-strong hover:underline" to={`/jobs/new?asset=${r.asset.id}`} onClick={(e) => e.stopPropagation()}>{t("garage.due.book")}</Link> },
        ]} />
    </div>
  );
}
