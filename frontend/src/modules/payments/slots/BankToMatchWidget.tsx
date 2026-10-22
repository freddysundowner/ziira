import { api, HomeBox, money, type SlotProps, unwrap, useCompany, useQuery, useTranslation } from "@/sdk";

import { RECONCILIATION_PATH } from "../public";

const WINDOW = 200;

/** Home box: money the bank or the mobile-money provider reports that no payment is matched to yet, and matches waiting for a yes. */
export default function BankToMatchWidget({ variant }: SlotProps) {
  const { t } = useTranslation("payments");
  const { company } = useCompany();
  const ask = (match_status: "unmatched" | "proposed") => unwrap(api.GET("/api/v1/payments/transactions", { params: { query: { match_status, limit: WINDOW } } }));
  const unmatched = useQuery({ queryKey: ["payments", "widget", "unmatched"], refetchInterval: 2 * 60_000, queryFn: () => ask("unmatched") });
  const proposed = useQuery({ queryKey: ["payments", "widget", "proposed"], refetchInterval: 2 * 60_000, queryFn: () => ask("proposed") });
  const rows = unmatched.data ?? [];
  const suggested = proposed.data?.length ?? 0;
  const error = unmatched.error ?? proposed.error;
  return (
    <HomeBox
      variant={variant} to={RECONCILIATION_PATH} value={`${rows.length}${rows.length >= WINDOW ? "+" : ""}`} tone={rows.length > 0 ? "warn" : undefined}
      loading={unmatched.isLoading || proposed.isLoading} error={error?.message} onRetry={() => { void unmatched.refetch(); void proposed.refetch(); }}
      clear={rows.length === 0 && suggested === 0 ? t("bankToMatch.nothing") : undefined}
      hint={suggested > 0 ? t("bankToMatch.suggested", { count: suggested }) : t("bankToMatch.hint")}
      rows={rows.slice(0, 5).map((r) => ({ key: r.id, left: r.counterparty_name ?? r.bill_ref ?? r.external_ref, right: money(r.amount, company?.currency) }))}
      openLabel={t("bankToMatch.open")} />
  );
}
