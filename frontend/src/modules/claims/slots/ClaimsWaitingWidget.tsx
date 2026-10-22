import { api, HomeBox, type SlotProps, unwrap, useQuery, useTranslation } from "@/sdk";

import { useClaimsCompany } from "../hooks";

const WINDOW = 200;

/** Home box: claims waiting on someone: the payer's answer to an estimate, or our answer to what they offered instead. */
export default function ClaimsWaitingWidget({ variant }: SlotProps) {
  const { t } = useTranslation("claims");
  const { companyId } = useClaimsCompany();
  const list = useQuery({
    queryKey: ["claims", "widget", companyId], enabled: !!companyId, refetchInterval: 2 * 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/claims/claims", { params: { query: { company_id: companyId, open_only: true, limit: WINDOW } } })),
  });
  const all = list.data ?? [];
  const withPayer = all.filter((c) => c.waiting_on === "payer");
  const toAnswer = all.filter((c) => c.waiting_on === "us");
  const waiting = [...toAnswer, ...withPayer];
  const more = all.length >= WINDOW;
  return (
    <HomeBox
      variant={variant} to="/claims" value={`${waiting.length}${more ? "+" : ""}`} tone={toAnswer.length > 0 ? "warn" : undefined}
      loading={list.isLoading || !companyId} error={list.error?.message} onRetry={() => void list.refetch()}
      clear={waiting.length === 0 ? t("widget.nothing") : undefined}
      hint={toAnswer.length > 0 ? t("widget.toAnswer", { count: toAnswer.length, withPayer: withPayer.length }) : t("widget.withPayer", { count: withPayer.length })}
      hintTone={toAnswer.length > 0 ? "warn" : undefined}
      rows={waiting.slice(0, 5).map((c) => ({ key: c.id, left: `${c.number} · ${c.payer_name}`, right: c.waiting_on === "us" ? t("widget.answerNeeded") : t("widget.payerSilent") }))}
      openLabel={t("widget.open")} />
  );
}
