import { Link } from "react-router-dom";

import { Alert, Badge, Card, formatDate, money, Skeleton, useTranslation } from "@/sdk";

import { useAsset, useVisits } from "../hooks";
import { jobHref } from "../public";
import { StageBadge } from "./StageBadge";

/** When an item comes in again: its last reading, whether its service is due, and what was done on earlier visits. */
export function ItemHistory({ assetId, currency }: { assetId: string; currency: string | undefined }) {
  const { t } = useTranslation("jobs");
  const asset = useAsset(assetId);
  const visits = useVisits(assetId);
  if (asset.isLoading || visits.isLoading) return <Skeleton className="h-24" />;
  const a = asset.data;
  if (!a) return null;
  const dueDays = a.service_due_in_days;
  const dueKm = a.service_due_in_odometer;
  const dueSoon = (dueDays != null && dueDays <= 30) || (dueKm != null && Number(dueKm) <= 1000);
  return (
    <Card title={t("garage.history.title")} description={a.odometer ? t("garage.history.lastReading", { reading: Number(a.odometer), date: a.odometer_at ? formatDate(a.odometer_at) : "" }) : undefined}>
      <div className="space-y-3">
        {(a.next_service_date || a.next_service_odometer) && (
          <Alert tone={dueSoon ? "warn" : "info"}>
            {t("garage.history.nextService", { date: a.next_service_date ? formatDate(a.next_service_date) : "—", reading: a.next_service_odometer ? Number(a.next_service_odometer) : "—" })}
            {dueDays != null && dueDays < 0 && ` ${t("garage.history.overdueDays", { n: -dueDays })}`}
            {dueKm != null && Number(dueKm) < 0 && ` ${t("garage.history.overdueKm", { n: -Number(dueKm) })}`}
          </Alert>
        )}
        {(visits.data ?? []).length === 0 ? <p className="text-sm text-muted">{t("garage.history.none")}</p> : (
          <ul className="divide-y divide-line text-sm">
            {(visits.data ?? []).map((v) => (
              <li key={v.job.id} className="py-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span><Link className="font-medium text-brand-strong hover:underline" to={jobHref(v.job.id)}>{v.job.number}</Link> · {v.job.title}</span>
                  <span className="inline-flex items-center gap-2 text-xs text-muted">{formatDate(v.job.received_at)}{v.odometer_in ? ` · ${Number(v.odometer_in)}` : ""}<StageBadge stage={v.job.status} />{v.job.is_rework && <Badge tone="warn">{t("card.returnVisit")}</Badge>}</span>
                </div>
                {v.work.length > 0 && <p className="mt-0.5 text-xs text-muted">{v.work.join(" · ")}{Number(v.total) > 0 ? ` · ${money(v.total, currency)}` : ""}</p>}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}
