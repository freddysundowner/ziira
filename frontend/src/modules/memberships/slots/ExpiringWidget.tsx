import { api, HomeBox, type SlotProps, unwrap, useCompany, useQuery, useTranslation } from "@/sdk";

/** Home box: memberships that end in the next 30 days (a cancellation that takes effect or a fixed end date), and session packages about to run out. */
export default function ExpiringWidget({ variant }: SlotProps) {
  const { t } = useTranslation("memberships");
  const { company } = useCompany();
  const companyId = company?.id ?? "";
  const summary = useQuery({
    queryKey: ["memberships", "widget", "summary", companyId], enabled: !!companyId, refetchInterval: 5 * 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/memberships/summary", { params: { query: { company_id: companyId } } })),
  });
  const s = summary.data;
  const ending = s?.ending_30_days ?? 0;
  const packages = s?.packages_expiring_30_days ?? 0;
  return (
    <HomeBox
      variant={variant} to="/memberships" value={ending} tone={ending > 0 ? "warn" : undefined}
      loading={summary.isLoading || !companyId} error={summary.error?.message} onRetry={() => void summary.refetch()}
      clear={s && ending === 0 && packages === 0 ? t("widget.nothingEnding") : undefined}
      hint={packages > 0 ? t("widget.endingPackages", { count: packages }) : t("widget.endingHint")}
      rows={s ? [
        { key: "ending", left: t("widget.rowEnding"), right: ending },
        { key: "renewing", left: t("widget.rowRenewing"), right: s.renewals_next_7_days },
        { key: "packages", left: t("widget.rowPackages"), right: packages },
      ] : []}
      openLabel={t("widget.openMembers")} />
  );
}
