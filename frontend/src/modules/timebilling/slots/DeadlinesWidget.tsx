import { api, formatDate, HomeBox, type SlotProps, today, unwrap, useQuery, useTranslation } from "@/sdk";

import { useWorkCompany } from "../hooks";

const WINDOW = 200;

/** The day `days` after `from` (YYYY-MM-DD), counted on the calendar so a time zone cannot move it. */
function plusDays(from: string, days: number): string {
  const d = new Date(`${from}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/** Home box: engagement work that is due within the next 7 days or already late, soonest first. */
export default function DeadlinesWidget({ variant }: SlotProps) {
  const { t } = useTranslation("timebilling");
  const { companyId } = useWorkCompany();
  const day = today();
  const list = useQuery({
    queryKey: ["timebilling", "widget", "deadlines", companyId, day], enabled: !!companyId, refetchInterval: 5 * 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/tasks", { params: { query: { company_id: companyId, status: "open", due_before: plusDays(day, 7), limit: WINDOW } } })),
  });
  const rows = list.data ?? [];
  const late = rows.filter((r) => r.overdue).length;
  return (
    <HomeBox
      variant={variant} to="/time/work" value={`${rows.length}${rows.length >= WINDOW ? "+" : ""}`} tone={late > 0 ? "bad" : undefined}
      loading={list.isLoading || !companyId} error={list.error?.message} onRetry={() => void list.refetch()}
      clear={rows.length === 0 ? t("widget.noDeadlines") : undefined}
      hint={late > 0 ? t("widget.deadlinesLate", { count: late }) : t("widget.deadlinesHint")}
      hintTone={late > 0 ? "bad" : undefined}
      rows={rows.slice(0, 5).map((r) => ({ key: r.id, left: `${r.name} · ${r.client_name || r.project_name}`, right: r.overdue ? t("widget.late") : formatDate(r.due_on) }))}
      openLabel={t("widget.openWork")} />
  );
}
