import { api, Badge, Button, DataTable, Drawer, formatDate, toast, unwrap, useMutation, usePagedList, useQueryClient, useTranslation, type Schemas } from "@/sdk";

import { Amount } from "./Amount";

/** Pick the payment that a provider transaction belongs to (for the ones the engine could not match by itself). */
export function MatchPayment({ txn, onClose }: { txn: Schemas["ExternalOut"] | null; onClose: () => void }) {
  const { t } = useTranslation("payments");
  const qc = useQueryClient();
  const list = usePagedList(["payments", "to-match", txn?.id], (limit, offset) =>
    unwrap(api.GET("/api/v1/payments/payments", { params: { query: { method: txn ? "mobile_money" : undefined, limit, offset } } })), 10);
  const match = useMutation({
    mutationFn: (paymentId: string) => unwrap(api.POST("/api/v1/payments/matches", { body: { external_transaction_id: txn?.id ?? "", payment_id: paymentId } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["transactions"] }); void qc.invalidateQueries({ queryKey: ["matches"] }); toast(t("matchSaved"), "ok"); onClose(); },
  });
  if (!txn) return null;
  return (
    <Drawer open onClose={onClose} title={t("matchToPayment")}>
      <p className="mb-1 text-sm text-muted">{t("matchExplain")}</p>
      <p className="mb-4 text-sm"><span className="font-mono text-xs">{txn.external_ref}</span> · <span className="font-semibold"><Amount value={txn.amount} /></span> · {formatDate(txn.txn_time, true)}</p>
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(p) => p.id} dense
        empty={{ title: t("noPaymentsToMatch"), hint: t("noPaymentsToMatchHint") }}
        columns={[
          { header: t("number"), cell: (p) => <span className="font-mono text-xs">{p.number}</span> },
          { header: t("date"), hideBelow: "sm", cell: (p) => formatDate(p.business_date) },
          { header: t("amount"), align: "right", cell: (p) => <Amount value={p.amount} companyId={p.company_id} /> },
          { header: "", align: "right", cell: (p) => (p.status === "posted" ? <Button size="sm" loading={match.isPending && match.variables === p.id} disabled={match.isPending} onClick={() => match.mutate(p.id)}>{t("match")}</Button> : <Badge>{p.status}</Badge>) },
        ]}
      />
    </Drawer>
  );
}
