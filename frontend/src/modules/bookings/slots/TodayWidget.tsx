import { Link } from "react-router-dom";

import { api, unwrap, useQuery, useTranslation } from "@/sdk";

import { useBranch } from "../hooks";
import { clock } from "../lib";

/** Home page box: how many appointments today, and the next few. */
export default function TodayWidget() {
  const { t } = useTranslation("bookings");
  const { branchId, zone } = useBranch();
  const desk = useQuery({
    queryKey: ["bookings", "front-desk", branchId], enabled: !!branchId, refetchInterval: 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/bookings/front-desk", { params: { query: { branch_id: branchId } } })),
  });
  if (desk.error) return <p className="text-sm text-bad">{desk.error.message}</p>;
  if (!desk.data) return <p className="text-sm text-muted">…</p>;
  const all = desk.data.appointments.filter((a) => a.status !== "cancelled");
  const waiting = all.filter((a) => a.status === "requested").length;
  const next = all.filter((a) => ["requested", "confirmed", "checked_in"].includes(a.status)).slice(0, 4);
  return (
    <div className="space-y-3">
      <div className="flex items-end justify-between gap-3">
        <div><p className="text-xs uppercase tracking-wide text-muted">{t("widget.today")}</p><p className="tnum text-2xl font-semibold">{all.length}</p></div>
        {waiting > 0 && <p className="text-sm font-medium text-warn">{t("widget.requests", { count: waiting })}</p>}
      </div>
      {next.length === 0 ? <p className="text-sm text-muted">{t("widget.none")}</p> : (
        <ul className="divide-y divide-line text-sm">
          {next.map((a) => (
            <li key={a.id} className="flex items-center justify-between gap-3 py-1.5">
              <span className="truncate"><span className="tnum font-medium">{clock(a.starts_at, zone)}</span> {a.kind === "class" ? a.service : a.client_name}</span>
              <span className="shrink-0 text-xs text-muted">{t(`status.${a.status}`)}</span>
            </li>
          ))}
        </ul>
      )}
      <Link to="/front-desk" className="inline-block text-xs font-medium text-brand-strong hover:underline">{t("widget.open")}</Link>
    </div>
  );
}
