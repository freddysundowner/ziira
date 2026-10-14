import { useState } from "react";
import { Link } from "react-router-dom";

import {
  api, Button, Card, DataTable, formatDate, Pager, PageHeader, toast, unwrap, useCan, useMutation, usePagedList, useQuery, useQueryClient, useTranslation,
} from "@/sdk";

import { Money } from "../components/Money";
import { ReasonDialog } from "../components/ReasonDialog";
import { SettleDrawer } from "../components/SettleDrawer";
import { Status } from "../components/Status";
import { SupplierName } from "../components/names";
import { useSupplier } from "../hooks";
import type { RefundDue } from "../types";

/** Money suppliers owe back on bills that were paid and then credited, and the refunds already received. */
export default function RefundsPage() {
  const { t } = useTranslation("purchasing");
  const qc = useQueryClient();
  const canPay = useCan("bills.pay");
  const [refunding, setRefunding] = useState<RefundDue | null>(null);
  const [reversing, setReversing] = useState<string | null>(null);
  const due = useQuery({ queryKey: ["purchasing", "refunds-due"], queryFn: () => unwrap(api.GET("/api/v1/purchasing/refunds-due")) });
  const list = usePagedList(["purchasing", "refunds"], (limit, offset) => unwrap(api.GET("/api/v1/purchasing/refunds", { params: { query: { limit, offset } } })));
  const reverse = useMutation({
    mutationFn: (v: { id: string; reason: string }) => unwrap(api.POST("/api/v1/purchasing/refunds/{refund_id}/reverse", { params: { path: { refund_id: v.id } }, body: { reason: v.reason } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["purchasing"] }); toast(t("refundReversed"), "ok"); setReversing(null); },
    onError: () => setReversing(null),
  });

  return (
    <>
      <PageHeader title={t("refunds")} description={t("refundsHint")} />
      <div className="space-y-4">
        <Card title={t("refundsDue")} description={t("refundsDueHint")} flush>
          <DataTable rows={due.data} loading={due.isLoading} error={due.error?.message} onRetry={() => void due.refetch()} rowKey={(r) => r.bill_id} empty={{ title: t("noRefundsDue") }}
            columns={[
              { header: t("bill"), cell: (r) => <Link className="font-mono text-xs font-medium text-brand hover:underline" to={`/bills/${r.bill_id}`}>{r.number}</Link> },
              { header: t("supplier"), cell: (r) => <SupplierName id={r.supplier_id} link /> },
              { header: t("paid"), hideBelow: "md", align: "right", cell: (r) => <Money value={r.amount_paid} /> },
              { header: t("credited"), hideBelow: "md", align: "right", cell: (r) => <Money value={r.credited} /> },
              { header: t("owedBack"), align: "right", cell: (r) => <span className="font-semibold"><Money value={r.owed_back} /></span> },
              { header: "", align: "right", cell: (r) => canPay && <Button size="sm" onClick={() => setRefunding(r)}>{t("recordRefundShort")}</Button> },
            ]} />
        </Card>
        <Card title={t("refundsReceived")} flush>
          <DataTable rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(r) => r.id} empty={{ title: t("noRefunds") }}
            columns={[
              { header: t("number"), cell: (r) => <span className="font-mono text-xs">{r.number}</span> },
              { header: t("supplier"), hideBelow: "sm", cell: (r) => <SupplierName id={r.supplier_id} /> },
              { header: t("receivedOn"), cell: (r) => formatDate(r.received_on) },
              { header: t("method"), hideBelow: "md", cell: (r) => t(`methods.${r.method}`, r.method) },
              { header: t("amount"), align: "right", cell: (r) => <Money value={r.amount} companyId={r.company_id} /> },
              { header: t("status"), cell: (r) => <Status status={r.status} /> },
              { header: "", align: "right", cell: (r) => canPay && r.status !== "reversed" && <Button size="sm" variant="ghost" onClick={() => setReversing(r.id)}>{t("reverseRefund")}</Button> },
            ]}
            footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />} />
        </Card>
      </div>
      {refunding && <RefundFromDue due={refunding} onClose={() => setRefunding(null)} />}
      {reversing && <ReasonDialog open onClose={() => setReversing(null)} title={t("reverseRefund")} message={t("reverseRefundHint")} confirmLabel={t("reverseRefund")} busy={reverse.isPending} onSubmit={(reason) => reverse.mutate({ id: reversing, reason })} />}
    </>
  );
}

/** The refund form for a bill from the "due" list, which does not carry its company: the supplier's company is used. */
function RefundFromDue({ due, onClose }: { due: RefundDue; onClose: () => void }) {
  const supplier = useSupplier(due.supplier_id);
  return <SettleDrawer open onClose={onClose} kind="refund" bill={{ id: due.bill_id, number: due.number, company_id: supplier.data?.company_id ?? "" }} defaultAmount={due.owed_back} />;
}
