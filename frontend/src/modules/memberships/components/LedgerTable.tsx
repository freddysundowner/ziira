import { api, DataTable, formatDate, unwrap, useQuery, useTranslation } from "@/sdk";

import { credits } from "../logic";

/** The credits ledger of one membership or package, newest first: every change of the balance and why. */
export function LedgerTable({ holderId, kind }: { holderId: string; kind: "member" | "package" }) {
  const { t } = useTranslation("memberships");
  const q = useQuery({
    queryKey: ["memberships", "ledger", holderId],
    queryFn: () => kind === "member"
      ? unwrap(api.GET("/api/v1/memberships/members/{member_id}/credits", { params: { path: { member_id: holderId }, query: { limit: 200 } } }))
      : unwrap(api.GET("/api/v1/memberships/sold-packages/{sold_id}/credits", { params: { path: { sold_id: holderId }, query: { limit: 200 } } })),
  });
  return (
    <DataTable rows={q.data} loading={q.isLoading} error={q.error?.message} onRetry={() => void q.refetch()} rowKey={(e) => e.id} dense
      empty={{ title: t("ledgerEmpty"), hint: t("ledgerEmptyHint") }}
      columns={[
        { header: t("date"), sortValue: (e) => e.created_at, cell: (e) => formatDate(e.business_date) },
        { header: t("what"), cell: (e) => <span className="font-medium">{t(`entryTypes.${e.entry_type}`, e.entry_type)}</span> },
        { header: t("credits"), align: "right", cell: (e) => <span className={Number(e.quantity) < 0 ? "text-bad" : "text-ok"}>{Number(e.quantity) > 0 ? "+" : ""}{credits(e.quantity)}</span> },
        { header: t("note"), hideBelow: "sm", cell: (e) => [e.note, e.service_ref, e.source_type].filter(Boolean).join(" · ") || "—" },
      ]} />
  );
}
