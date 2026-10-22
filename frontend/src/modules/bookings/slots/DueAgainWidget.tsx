import { api, HomeBox, type SlotProps, unwrap, useQuery, useTranslation } from "@/sdk";

import { useBranch } from "../hooks";

const WINDOW = 200;

/** Home box: clients due for their service again who have nothing booked (the recall list). */
export default function DueAgainWidget({ variant }: SlotProps) {
  const { t } = useTranslation("bookings");
  const { companyId } = useBranch();
  const list = useQuery({
    queryKey: ["bookings", "recalls", "widget", companyId], enabled: !!companyId, refetchInterval: 5 * 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/bookings/recalls", { params: { query: { company_id: companyId, limit: WINDOW } } })),
  });
  const rows = list.data ?? [];
  const late = rows.filter((r) => r.overdue_days > 0).length;
  return (
    <HomeBox
      variant={variant} to="/recalls" value={`${rows.length}${rows.length >= WINDOW ? "+" : ""}`} tone={late > 0 ? "warn" : undefined}
      loading={list.isLoading || !companyId} error={list.error?.message} onRetry={() => void list.refetch()}
      clear={rows.length === 0 ? t("widget.nobodyDue") : undefined}
      hint={late > 0 ? t("widget.overdueCount", { count: late }) : t("widget.dueSoon")}
      rows={rows.slice(0, 5).map((r) => ({ key: `${r.customer_id}:${r.offer_id}`, left: `${r.client_name ?? "—"} · ${r.service}`, right: r.overdue_days > 0 ? t("widget.daysLate", { count: r.overdue_days }) : t("widget.dueToday") }))}
      openLabel={t("widget.openRecalls")} />
  );
}
