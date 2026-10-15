import { Plus, X } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import {
  api, Button, DataTable, DetailList, Drawer, EmptyState, ErrorState, formatDate, humanise, Modal, PageHeader, Pager, Skeleton, toast, unwrap, useCan, useMutation, useQuery,
  useQueryClient, usePagedList, useTranslation,
} from "@/sdk";

import { useBranches, useMoney } from "../hooks";
import { DocStatus } from "./DocStatus";
import { DocsTabs } from "./DocsTabs";
import { CustomerName, CustomerPicker } from "./hooks";
import { isPositive, receiptActions } from "./lib";
import { ReasonDialog } from "./ReasonDialog";
import { RefundReceipt } from "./RefundReceipt";

/** Money given back to customers from what they paid in advance. Refunds are made from a payment held on account. */
export default function RefundsPage() {
  const { t } = useTranslation("pos");
  const [params, setParams] = useSearchParams();
  const open = params.get("open");
  const canReceive = useCan("receivables.manage");
  const [customer, setCustomer] = useState("");
  const [creating, setCreating] = useState(false);
  const { nameOf, branches } = useBranches();
  const m = useMoney();
  const list = usePagedList(["pos-docs", "refunds", customer], (limit, offset) =>
    unwrap(api.GET("/api/v1/pos/refunds", { params: { query: { customer_id: customer || undefined, limit, offset } } })));

  return (
    <>
      <PageHeader title={t("docs.title")} description={t("docs.hint.refund")}
        actions={canReceive && <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" />{t("docs.newRefund")}</Button>} />
      <DocsTabs />
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()}
        rowKey={(r) => r.id} rowHref={(r) => `/pos/refunds?open=${r.id}`}
        toolbar={(
          <>
            <div className="w-56"><CustomerPicker value={customer} onChange={setCustomer} clearable placeholder={t("docs.allCustomers")} /></div>
            {customer && <Button variant="ghost" onClick={() => setCustomer("")}><X className="h-4 w-4" />{t("clearFilters")}</Button>}
          </>
        )}
        empty={{ title: customer ? t("docs.noMatch.refund") : t("docs.none.refund"), hint: customer ? t("tryOtherFilters") : t("docs.noneHint.refund") }}
        columns={[
          { header: t("number"), cell: (r) => <span className="font-mono text-xs font-medium">{r.number}</span> },
          { header: t("docs.customer"), cell: (r) => <CustomerName id={r.customer_id} /> },
          { header: t("docs.refundedOn"), hideBelow: "sm", cell: (r) => formatDate(r.refunded_on) },
          { header: t("method"), hideBelow: "md", cell: (r) => t(`docs.refundVia.${r.method}`, humanise(r.method)) },
          ...(branches.length > 1 ? [{ header: t("branch"), hideBelow: "lg" as const, cell: (r: { branch_id: string | null }) => nameOf(r.branch_id) }] : []),
          { header: t("amount"), align: "right", cell: (r) => m(r.amount, r.company_id) },
          { header: t("status"), cell: (r) => <DocStatus status={r.status} /> },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
      {open && <RefundDetail refundId={open} onClose={() => setParams({}, { replace: true })} />}
      <NewRefund open={creating} onClose={() => setCreating(false)} />
    </>
  );
}

function RefundDetail({ refundId, onClose }: { refundId: string; onClose: () => void }) {
  const { t } = useTranslation("pos");
  const qc = useQueryClient();
  const m = useMoney();
  const canReceive = useCan("receivables.manage");
  const [reversing, setReversing] = useState(false);
  const refund = useQuery({ queryKey: ["pos-refund", refundId], queryFn: () => unwrap(api.GET("/api/v1/pos/refunds/{refund_id}", { params: { path: { refund_id: refundId } } })) });
  const reverse = useMutation({
    mutationFn: (reason: string) => unwrap(api.POST("/api/v1/pos/refunds/{refund_id}/reverse", { params: { path: { refund_id: refundId } }, body: { reason } })),
    onSuccess: (r) => {
      for (const key of ["pos-refund", "pos-docs", "pos-receipt", "customer-balance", "customer-statement"]) void qc.invalidateQueries({ queryKey: [key] });
      toast(t("docs.refundReversed", { number: r.number }), "ok");
      setReversing(false);
    },
    onError: () => setReversing(false),
  });
  const r = refund.data;
  return (
    <>
      <Drawer open onClose={onClose} title={r ? t("docs.refundNumber", { number: r.number }) : t("docs.tabs.refunds")} footer={<Button variant="secondary" onClick={onClose}>{t("close")}</Button>}>
        {refund.error ? <ErrorState message={refund.error.message} onRetry={() => void refund.refetch()} />
          : !r ? <Skeleton className="h-40 w-full" />
          : (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-2"><DocStatus status={r.status} /><span className="tnum text-lg font-semibold">{m(r.amount, r.company_id)}</span></div>
              <DetailList items={[
                { label: t("docs.customer"), value: <CustomerName id={r.customer_id} link /> },
                { label: t("docs.refundedOn"), value: formatDate(r.refunded_on) },
                { label: t("method"), value: t(`docs.refundVia.${r.method}`, humanise(r.method)) },
                { label: t("reason"), value: r.reason },
                { label: t("docs.fromPayment"), value: <Link className="text-brand-strong hover:underline" to={`/pos/receipts?open=${r.receipt_id}`}>{t("docs.viewPayment")}</Link> },
              ]} />
              {canReceive && r.status === "posted" && <Button variant="danger" onClick={() => setReversing(true)}>{t("docs.reverse")}</Button>}
            </div>
          )}
      </Drawer>
      {r && <ReasonDialog open={reversing} onClose={() => setReversing(false)} busy={reverse.isPending} title={t("docs.reverseRefundTitle", { number: r.number })}
        message={t("docs.reverseRefundAsk")} confirmLabel={t("docs.reverse")} onConfirm={(reason) => reverse.mutate(reason)} />}
    </>
  );
}

/** Pick a customer, then one of their payments that still holds money on account, and give it back. */
function NewRefund({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation("pos");
  const m = useMoney();
  const [customer, setCustomer] = useState("");
  const [chosen, setChosen] = useState<string | null>(null);
  const payments = useQuery({
    enabled: open && Boolean(customer), queryKey: ["pos-docs", "refundable", customer],
    queryFn: () => unwrap(api.GET("/api/v1/pos/receipts", { params: { query: { customer_id: customer, limit: 100 } } })),
  });
  const held = payments.data?.filter((r) => receiptActions(r).refund) ?? [];
  const receipt = held.find((r) => r.id === chosen);
  const close = () => { setCustomer(""); setChosen(null); onClose(); };

  return (
    <>
      <Modal open={open && !receipt} onClose={close} title={t("docs.newRefund")} footer={<Button variant="secondary" onClick={close}>{t("close")}</Button>}>
        <p className="mb-3 text-sm text-muted">{t("docs.newRefundHint")}</p>
        <CustomerPicker value={customer} onChange={(id) => { setCustomer(id); setChosen(null); }} />
        <div className="mt-4">
          {!customer ? null
            : payments.error ? <ErrorState message={payments.error.message} onRetry={() => void payments.refetch()} />
            : !payments.data ? <Skeleton className="h-24 w-full" />
            : held.length === 0 ? <EmptyState title={t("docs.nothingHeld")} hint={t("docs.nothingHeldHint")} />
            : (
              <ul className="divide-y divide-line rounded-lg border border-line">
                {held.map((r) => (
                  <li key={r.id} className="flex items-center justify-between gap-3 p-3 text-sm">
                    <span><span className="font-mono text-xs font-medium">{r.number}</span> <span className="text-muted">{formatDate(r.received_on)}</span></span>
                    <span className="flex items-center gap-3"><span className="tnum">{isPositive(r.unallocated) ? m(r.unallocated, r.company_id) : ""}</span>
                      <Button size="sm" variant="secondary" onClick={() => setChosen(r.id)}>{t("docs.giveBack")}</Button></span>
                  </li>
                ))}
              </ul>
            )}
        </div>
      </Modal>
      {receipt && <RefundReceipt receipt={receipt} open onClose={close} />}
    </>
  );
}
