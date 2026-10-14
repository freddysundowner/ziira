import { Link } from "react-router-dom";

import { api, formatDate, StatusBadge, unwrap, useCan, useQuery, useTranslation } from "@/sdk";

/** Home box: leave waiting for a decision, and the latest payroll run with its status. */
export default function PeopleWidget() {
  const { t } = useTranslation("people");
  const canLeave = useCan("leave.approve");
  const canPayroll = useCan("payroll.view");
  const pending = useQuery({
    enabled: canLeave, queryKey: ["people", "widget", "pending-leave"],
    queryFn: () => unwrap(api.GET("/api/v1/people/leave-requests", { params: { query: { status: "pending", limit: 100 } } })),
  });
  const runs = useQuery({
    enabled: canPayroll, queryKey: ["people", "widget", "latest-run"],
    queryFn: () => unwrap(api.GET("/api/v1/people/payroll-runs", { params: { query: { limit: 1 } } })),
  });
  const run = runs.data?.[0];
  const count = pending.data?.length ?? 0;
  if (pending.error || runs.error) return <p className="text-sm text-muted">{t("widget.unavailable")}</p>;

  return (
    <ul className="space-y-3 text-sm">
      {canLeave && (
        <li className="flex items-center justify-between gap-3">
          <span>{pending.isLoading ? "…" : count === 0 ? t("widget.noLeave") : t("widget.leaveWaiting", { count })}</span>
          {count > 0 && <Link className="font-medium text-brand-strong hover:underline" to="/leave">{t("widget.review")}</Link>}
        </li>
      )}
      {canPayroll && (
        <li className="flex items-center justify-between gap-3">
          {runs.isLoading ? "…" : run ? (
            <>
              <span>{t("widget.latestRun", { start: formatDate(run.period_start), end: formatDate(run.period_end) })}</span>
              <Link to={`/payroll/${run.id}`}><StatusBadge status={run.status} /></Link>
            </>
          ) : <span className="text-muted">{t("widget.noRuns")}</span>}
        </li>
      )}
    </ul>
  );
}
