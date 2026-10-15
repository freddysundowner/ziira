import { HandCoins, Printer, Undo2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import {
  Alert, api, Button, ConfirmDialog, DataTable, DetailList, Drawer, ErrorState, formatDate, humanise, Skeleton, toast, unwrap, useCan, useMutation, useQuery, useQueryClient,
  useTranslation,
} from "@/sdk";

import { useBranches, useMoney } from "../hooks";
import { DocStatus } from "./DocStatus";
import { CustomerName } from "./hooks";
import { receiptActions } from "./lib";
import { PrintDocument } from "./PrintDocument";
import { ReasonDialog } from "./ReasonDialog";
import { RefundReceipt } from "./RefundReceipt";

/** A customer payment: what it settled, what is held on account, and its actions (print, reverse, give back, apply to invoices). */
export function ReceiptDetail({ receiptId, onClose }: { receiptId: string; onClose: () => void }) {
  const { t } = useTranslation("pos");
  const qc = useQueryClient();
  const m = useMoney();
  const { nameOf } = useBranches();
  const canReceive = useCan("receivables.manage");
  const [printing, setPrinting] = useState(false);
  const [reversing, setReversing] = useState(false);
  const [refunding, setRefunding] = useState(false);
  const [applying, setApplying] = useState(false);
  const receipt = useQuery({ queryKey: ["pos-receipt", receiptId], queryFn: () => unwrap(api.GET("/api/v1/pos/receipts/{receipt_id}", { params: { path: { receipt_id: receiptId } } })) });
  const r = receipt.data;

  const refresh = () => { for (const key of ["pos-receipt", "pos-docs", "pos-invoice", "customer-balance", "customer-statement", "customer-receipts", "customer-invoices"]) void qc.invalidateQueries({ queryKey: [key] }); };
  const reverse = useMutation({
    mutationFn: (reason: string) => unwrap(api.POST("/api/v1/pos/receipts/{receipt_id}/reverse", { params: { path: { receipt_id: receiptId } }, body: { reason } })),
    onSuccess: (x) => { refresh(); toast(t("docs.receiptReversed", { number: x.number }), "ok"); setReversing(false); },
    onError: () => setReversing(false),
  });
  const apply = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/pos/customers/{customer_id}/apply-credit", { params: { path: { customer_id: r?.customer_id ?? "" } }, body: { allocations: null } })),
    onSuccess: (done) => { refresh(); toast(done.length ? t("docs.applied", { count: done.length }) : t("docs.appliedNone"), done.length ? "ok" : "warn"); setApplying(false); },
    onError: () => setApplying(false),
  });
  const can = r ? receiptActions(r) : null;

  return (
    <>
      <Drawer open onClose={onClose} title={r ? t("docs.receiptTitle", { number: r.number }) : t("docs.tabs.receipts")}
        footer={<Button variant="secondary" onClick={onClose}>{t("close")}</Button>}>
        {receipt.error ? <ErrorState message={receipt.error.message} onRetry={() => void receipt.refetch()} />
          : !r || !can ? <Skeleton className="h-48 w-full" />
          : (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-2"><DocStatus status={r.status} /><span className="tnum text-lg font-semibold">{m(r.amount, r.company_id)}</span></div>
              <DetailList items={[
                { label: t("docs.customer"), value: <CustomerName id={r.customer_id} link /> },
                { label: t("docs.receivedOn"), value: formatDate(r.received_on) },
                { label: t("method"), value: t(`docs.payVia.${r.method}`, humanise(r.method)) },
                { label: t("reference"), value: r.reference ?? "—" },
                { label: t("branch"), value: nameOf(r.branch_id) },
                { label: t("docs.heldOnAccount"), value: m(r.unallocated, r.company_id) },
                { label: t("docs.refundedSoFar"), value: m(r.refunded, r.company_id) },
              ]} />
              <div>
                <h3 className="mb-2 text-sm font-semibold">{t("docs.settled")}</h3>
                <DataTable rows={r.allocations} rowKey={(a) => a.invoice_id} empty={{ title: t("docs.settledNone"), hint: t("docs.settledNoneHint") }} dense
                  columns={[
                    { header: t("docs.invoice"), cell: (a) => <InvoiceLink id={a.invoice_id} /> },
                    { header: t("amount"), align: "right", cell: (a) => m(a.amount, r.company_id) },
                  ]} />
              </div>
              {canReceive && !can.reverse && r.status === "posted" && <Alert tone="info">{t("docs.cannotReverseRefunded")}</Alert>}
              <div className="flex flex-wrap gap-2">
                <Button variant="secondary" onClick={() => setPrinting(true)}><Printer className="h-4 w-4" />{t("print")}</Button>
                {canReceive && can.applyCredit && <Button variant="secondary" onClick={() => setApplying(true)}><HandCoins className="h-4 w-4" />{t("docs.applyCredit")}</Button>}
                {canReceive && can.refund && <Button variant="secondary" onClick={() => setRefunding(true)}><Undo2 className="h-4 w-4" />{t("docs.giveBack")}</Button>}
                {canReceive && can.reverse && <Button variant="danger" onClick={() => setReversing(true)}>{t("docs.reverse")}</Button>}
              </div>
            </div>
          )}
      </Drawer>
      {r && (
        <>
          <PrintDocument kind="receipt" id={r.id} companyId={r.company_id} open={printing} onClose={() => setPrinting(false)} />
          <ReasonDialog open={reversing} onClose={() => setReversing(false)} busy={reverse.isPending} title={t("docs.reverseReceiptTitle", { number: r.number })}
            message={t("docs.reverseReceiptAsk")} confirmLabel={t("docs.reverse")} onConfirm={(reason) => reverse.mutate(reason)} />
          <RefundReceipt receipt={r} open={refunding} onClose={() => setRefunding(false)} />
          <ConfirmDialog open={applying} onClose={() => setApplying(false)} busy={apply.isPending} title={t("docs.applyCredit")} confirmLabel={t("docs.applyCredit")}
            message={t("docs.applyAsk", { held: m(r.unallocated, r.company_id) })} onConfirm={() => apply.mutate()} />
        </>
      )}
    </>
  );
}

/** An invoice's number from its id, as a link. */
function InvoiceLink({ id }: { id: string }) {
  const invoice = useQuery({
    retry: false, staleTime: 60_000, queryKey: ["pos-invoice-number", id],
    queryFn: () => unwrap(api.GET("/api/v1/pos/invoices/{invoice_id}", { params: { path: { invoice_id: id } } })),
  });
  return <Link className="font-mono text-xs font-medium text-brand-strong hover:underline" to={`/pos/invoices/${id}`}>{invoice.data?.number ?? id.slice(0, 8)}</Link>;
}
