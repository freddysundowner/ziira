import { Link } from "react-router-dom";

import { api, unwrap, useQuery, useTranslation } from "@/sdk";

import { useJobsCompany } from "../hooks";

/** Home page box: items waiting to be collected and jobs past their promised date. */
export default function ReadyWidget() {
  const { t } = useTranslation("jobs");
  const { companyId } = useJobsCompany();
  const board = useQuery({
    queryKey: ["jobs", "widget", companyId], enabled: !!companyId, refetchInterval: 120_000,
    queryFn: () => unwrap(api.GET("/api/v1/jobs/jobs/board", { params: { query: { company_id: companyId } } })),
  });
  if (board.error) return <p className="text-sm text-bad">{board.error.message}</p>;
  if (!board.data) return <p className="text-sm text-muted">…</p>;
  const live = board.data.jobs.filter((j) => j.status.kind === "open" || j.status.kind === "waiting");
  const ready = board.data.jobs.filter((j) => j.status.role === "ready");
  const late = live.filter((j) => j.overdue);
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-3">
        <div><p className="text-xs uppercase tracking-wide text-muted">{t("widget.open")}</p><p className="tnum text-2xl font-semibold">{live.length}</p></div>
        <div><p className="text-xs uppercase tracking-wide text-muted">{t("widget.ready")}</p><p className="tnum text-2xl font-semibold">{ready.length}</p></div>
        <div><p className="text-xs uppercase tracking-wide text-muted">{t("widget.late")}</p><p className={`tnum text-2xl font-semibold ${late.length ? "text-bad" : ""}`}>{late.length}</p></div>
      </div>
      <Link to="/jobs" className="inline-block text-xs font-medium text-brand-strong hover:underline">{t("widget.openBoard")}</Link>
    </div>
  );
}
