import { useState } from "react";

import {
  api, Alert, Badge, Button, DataTable, DetailList, Drawer, Field, formatDate, humanise, StatusBadge, Textarea, toast, unwrap, useCan, useMutation, useQuery,
  useQueryClient, useTranslation, type Schemas,
} from "@/sdk";

import { matchTone } from "../logic";
import { Amount } from "./Amount";
import { usePaymentAccounts } from "./usePaymentAccounts";

/** One payment: its details, what it was matched to, and a reason-required reversal. */
export function PaymentDetail({ payment, onClose }: { payment: Schemas["PaymentOut"] | null; onClose: () => void }) {
  const { t } = useTranslation("payments");
  const qc = useQueryClient();
  const canRecord = useCan("payments.record");
  const accounts = usePaymentAccounts({ includeInactive: true });
  const [reversing, setReversing] = useState(false);
  const [reason, setReason] = useState("");
  const id = payment?.id ?? "";
  const matches = useQuery({
    enabled: !!payment, queryKey: ["payment-matches", id],
    queryFn: () => unwrap(api.GET("/api/v1/payments/matches", { params: { query: { payment_id: id } } })),
  });
  const reverse = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/payments/payments/{payment_id}/reverse", { params: { path: { payment_id: id } }, body: { reason: reason.trim() } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["payments"] }); void qc.invalidateQueries({ queryKey: ["payment-matches"] }); toast(t("reversed"), "ok"); setReversing(false); setReason(""); onClose(); },
  });

  if (!payment) return null;
  const account = accounts.data?.find((a) => a.id === payment.payment_account_id);
  return (
    <Drawer open onClose={onClose} title={payment.number}
      footer={canRecord && payment.status === "posted" ? <Button variant="danger" onClick={() => setReversing(true)}>{t("reverse")}</Button> : undefined}>
      <div className="space-y-5">
        <div className="flex items-center gap-2"><StatusBadge status={payment.status} /><Badge tone={payment.direction === "in" ? "ok" : "warn"}>{t(`directions.${payment.direction}`)}</Badge></div>
        <p className="tnum text-3xl font-semibold"><Amount value={payment.amount} companyId={payment.company_id} /></p>
        <DetailList items={[
          { label: t("method"), value: t(`methods.${payment.method}`, humanise(payment.method)) },
          { label: t("account"), value: account?.name },
          { label: t("date"), value: formatDate(payment.business_date) },
          { label: t("reference"), value: payment.external_ref },
          { label: t("party"), value: payment.party_type ? t(`parties.${payment.party_type}`, payment.party_type) : null },
        ]} />
        {payment.status === "reversed" && <Alert tone="warn">{t("reversedNote")}</Alert>}
        <div>
          <h3 className="mb-2 text-sm font-semibold">{t("matchedTo")}</h3>
          <DataTable
            rows={matches.data} loading={matches.isLoading} error={matches.error?.message} onRetry={() => void matches.refetch()} rowKey={(m) => m.id} dense
            empty={{ title: t("noMatches"), hint: t("noMatchesHint") }}
            columns={[
              { header: t("amount"), align: "right", cell: (m) => <Amount value={m.amount} companyId={payment.company_id} /> },
              { header: t("how"), cell: (m) => t(`stages.${m.stage}`, humanise(m.stage)) },
              { header: t("status"), cell: (m) => <Badge tone={matchTone(m.status)}>{t(`matchStatuses.${m.status}`, m.status)}</Badge> },
            ]}
          />
        </div>
      </div>
      <Drawer open={reversing} onClose={() => setReversing(false)} title={t("reversePayment")}
        footer={<><Button variant="secondary" onClick={() => setReversing(false)}>{t("cancel")}</Button><Button variant="danger" disabled={!reason.trim()} loading={reverse.isPending} onClick={() => reverse.mutate()}>{t("reverse")}</Button></>}>
        <p className="mb-4 text-sm text-muted">{t("reverseAsk", { number: payment.number })}</p>
        <Field label={t("reason")} required><Textarea value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} autoFocus /></Field>
      </Drawer>
    </Drawer>
  );
}
