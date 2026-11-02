import { Link } from "react-router-dom";

import { api, Button, Card, formatDate, unwrap, useQuery, useTranslation } from "@/sdk";

import { useUnit } from "../hooks";

/** Today's booked appointments that have not been taken in yet: one click starts the intake with the customer filled in. */
export function BookedVisits({ branchId }: { branchId: string }) {
  const { t } = useTranslation("jobs");
  const hasBookings = useUnit("bookings");
  const waiting = useQuery({
    queryKey: ["jobs", "booked-visits", branchId], enabled: hasBookings && !!branchId, refetchInterval: 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/jobs/appointments/waiting", { params: { query: { branch_id: branchId } } })),
  });
  if (!hasBookings || !waiting.data || waiting.data.length === 0) return null;
  return (
    <Card title={t("floor.booked.title")} className="mb-4" flush>
      <ul className="divide-y divide-line">
        {waiting.data.map((v) => (
          <li key={v.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 text-sm">
            <span><span className="font-medium">{v.customer_name ?? v.number}</span><span className="ml-2 text-muted">{formatDate(v.starts_at, true)} · {v.number}</span></span>
            <Link to={`/jobs/new?appointment=${v.id}${v.customer_id ? `&customer=${v.customer_id}` : ""}`}><Button size="sm" variant="secondary">{t("floor.booked.takeIn")}</Button></Link>
          </li>
        ))}
      </ul>
    </Card>
  );
}
