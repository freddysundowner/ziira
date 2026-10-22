import { api, HomeBox, type SlotProps, unwrap, useCompany, useQuery, useTranslation } from "@/sdk";

import { checkinPath } from "../public";

/** Home box: how many people came in today, and how many were turned away. */
export default function CheckinsTodayWidget({ variant }: SlotProps) {
  const { t } = useTranslation("memberships");
  const { company } = useCompany();
  const companyId = company?.id ?? "";
  const today = useQuery({
    queryKey: ["memberships", "widget", "checkins", companyId], enabled: !!companyId, refetchInterval: 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/memberships/checkin/today", { params: { query: { company_id: companyId } } })),
  });
  const d = today.data;
  return (
    <HomeBox
      variant={variant} to={checkinPath} value={d?.visits ?? 0}
      loading={today.isLoading || !companyId} error={today.error?.message} onRetry={() => void today.refetch()}
      hint={d && d.refused > 0 ? t("widget.refused", { count: d.refused }) : t("widget.noRefusals")}
      hintTone={d && d.refused > 0 ? "warn" : undefined}
      clear={d && d.visits === 0 && d.refused === 0 ? t("widget.noCheckins") : undefined}
      openLabel={t("widget.openCheckin")} />
  );
}
