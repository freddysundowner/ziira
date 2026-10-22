import { api, HomeBox, type SlotProps, unwrap, useQuery, useSession, useTranslation } from "@/sdk";

import { useJobsCompany } from "../hooks";

export type WaitingKind = "approval" | "parts" | "insurer";

/** The live jobs of the company's board, shared by the Home boxes (same request as the jobs box). */
export function useWidgetBoard() {
  const { companyId } = useJobsCompany();
  const board = useQuery({
    queryKey: ["jobs", "widget", companyId], enabled: !!companyId, refetchInterval: 120_000,
    queryFn: () => unwrap(api.GET("/api/v1/jobs/jobs/board", { params: { query: { company_id: companyId } } })),
  });
  return { board, companyId };
}

/** Home box for jobs held up by something: an estimate nobody has approved, parts that have not arrived, or the insurer's answer. */
export function WaitingBox({ kind, variant }: SlotProps & { kind: WaitingKind }) {
  const { t } = useTranslation("jobs");
  const { board, companyId } = useWidgetBoard();
  const hasClaims = useSession().enabledUnits.has("claims");
  const jobs = (board.data?.jobs ?? []).filter((j) => j.waiting_on.includes(kind));
  const late = jobs.filter((j) => j.overdue).length;
  const more = !!board.data?.truncated;
  if (kind === "insurer" && !hasClaims) return null;      // no Claims unit, nobody to wait for: the box is left out
  return (
    <HomeBox
      variant={variant} to="/jobs" value={`${jobs.length}${more ? "+" : ""}`} tone={late > 0 ? "warn" : undefined}
      loading={board.isLoading || !companyId} error={board.error?.message} onRetry={() => void board.refetch()}
      clear={jobs.length === 0 ? t(`widget.nothing.${kind}`) : undefined}
      hint={late > 0 ? t("widget.lateOnes", { count: late }) : t(`widget.hint.${kind}`)}
      rows={jobs.slice(0, 5).map((j) => ({ key: j.id, left: `${j.number} · ${j.asset?.label ?? j.title}`, right: j.days_in_status > 0 ? t("widget.days", { count: j.days_in_status }) : t("widget.today") }))}
      openLabel={t("widget.openBoard")} />
  );
}
