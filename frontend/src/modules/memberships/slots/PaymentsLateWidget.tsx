import { api, HomeBox, money, type SlotProps, unwrap, useCompany, useCurrency, useQuery, useTranslation } from "@/sdk";

import { sumDecimals } from "../logic";
import { arrearsPath } from "../public";

const WINDOW = 100;

/** Home box: members who owe money, and how much. */
export default function PaymentsLateWidget({ variant }: SlotProps) {
  const { t } = useTranslation("memberships");
  const { company } = useCompany();
  const companyId = company?.id ?? "";
  const currency = useCurrency(companyId || undefined);
  const list = useQuery({
    queryKey: ["memberships", "widget", "arrears", companyId], enabled: !!companyId, refetchInterval: 5 * 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/memberships/arrears", { params: { query: { company_id: companyId, min_days: 1, limit: WINDOW } } })),
  });
  const rows = list.data ?? [];
  const owed = sumDecimals(rows.map((r) => r.owed));
  const more = rows.length >= WINDOW;
  return (
    <HomeBox
      variant={variant} to={arrearsPath} value={`${rows.length}${more ? "+" : ""}`} tone={rows.length > 0 ? "bad" : undefined}
      loading={list.isLoading || !companyId} error={list.error?.message} onRetry={() => void list.refetch()}
      clear={rows.length === 0 ? t("widget.nobodyLate") : undefined}
      hint={t(more ? "widget.owedAtLeast" : "widget.owed", { amount: money(owed, currency) })}
      rows={rows.slice(0, 5).map((r) => ({ key: r.customer_id, left: r.customer_name ?? "—", right: money(r.owed, currency) }))}
      openLabel={t("widget.openArrears")} />
  );
}
