import { Link } from "react-router-dom";

import { api, Figure, type SlotProps, StatRow, unwrap, useQuery, useTranslation } from "@/sdk";

import { useJobsCompany } from "../hooks";

/** Home page box: items waiting to be collected and jobs past their promised date. */
export default function ReadyWidget({ variant }: SlotProps) {
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
  const figures = (
    <StatRow>
      <Figure label={t("widget.open")} value={live.length} />
      <Figure label={t("widget.ready")} value={ready.length} />
      <Figure label={t("widget.late")} value={late.length} tone={late.length ? "bad" : undefined} />
    </StatRow>
  );
  if (variant === "stat") return <Link to="/jobs" className="block" title={t("widget.openBoard")}>{figures}</Link>;
  return (
    <div className="space-y-2">
      {figures}
      <Link to="/jobs" className="inline-block text-xs font-medium text-brand-strong hover:underline">{t("widget.openBoard")}</Link>
    </div>
  );
}
