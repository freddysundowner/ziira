import { Banknote, FilePlus2, Pencil, Printer, Undo2 } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  Alert, api, Button, Card, ConfirmDialog, DataTable, DetailList, ErrorState, formatDate, Menu, money, PageHeader, quantity, Skeleton, toast, today, unwrap, useCan,
  useCurrency, useMutation, useQuery, useQueryClient, useTranslation,
} from "@/sdk";

import { ApprovalBar } from "../components/ApprovalBar";
import { CreditNoteDrawer } from "../components/CreditNoteDrawer";
import { ExceptionPanel } from "../components/ExceptionPanel";
import { Money } from "../components/Money";
import { ProductName, SupplierName } from "../components/names";
import { ReasonDialog } from "../components/ReasonDialog";
import { SettleDrawer } from "../components/SettleDrawer";
import { Status } from "../components/Status";
import { Totals } from "../components/Totals";
import { amountDue, isOpenBill, isOverdue } from "../lib";
import type { Bill } from "../types";

type Confirm = "submit" | "cancel" | null;

export default function BillPage() {
  const { t } = useTranslation("purchasing");
  const { billId = "" } = useParams();
  const qc = useQueryClient();
  const canBill = useCan("bills.manage");
  const canApprove = useCan("bills.approve");
  const canPay = useCan("bills.pay");
  const [confirm, setConfirm] = useState<Confirm>(null);
  const [paying, setPaying] = useState(false);
  const [refunding, setRefunding] = useState(false);
  const [crediting, setCrediting] = useState(false);
  const [reversing, setReversing] = useState(false);
  const [reversingPayment, setReversingPayment] = useState<string | null>(null);

  const bill = useQuery({ queryKey: ["purchasing", "bill", billId], queryFn: () => unwrap(api.GET("/api/v1/purchasing/bills/{bill_id}", { params: { path: { bill_id: billId } } })) });
  const b = bill.data;
  const currency = useCurrency(b?.company_id);
  const posted = !!b && ["posted", "part_paid", "paid"].includes(b.status);
  const payments = useQuery({ enabled: posted, queryKey: ["purchasing", "bill-payments", billId], queryFn: () => unwrap(api.GET("/api/v1/purchasing/bills/{bill_id}/payments", { params: { path: { bill_id: billId } } })) });
  const credits = useQuery({ enabled: posted, queryKey: ["purchasing", "credit-notes", { bill: billId }], queryFn: () => unwrap(api.GET("/api/v1/purchasing/credit-notes", { params: { query: { bill_id: billId, limit: 50 } } })) });
  const refundsDue = useQuery({ enabled: posted && canPay, queryKey: ["purchasing", "refunds-due"], queryFn: () => unwrap(api.GET("/api/v1/purchasing/refunds-due")) });
  const owedBack = refundsDue.data?.find((r) => r.bill_id === billId)?.owed_back;

  const done = (key: string) => { void qc.invalidateQueries({ queryKey: ["purchasing"] }); toast(t(key), "ok"); setConfirm(null); setReversing(false); setReversingPayment(null); };
  const run = useMutation({
    mutationFn: (action: "submit" | "cancel") => {
      const params = { params: { path: { bill_id: billId } } };
      return action === "submit" ? unwrap(api.POST("/api/v1/purchasing/bills/{bill_id}/submit", params)) : unwrap(api.POST("/api/v1/purchasing/bills/{bill_id}/cancel", params));
    },
    onSuccess: (_, action) => done(action === "submit" ? "billSubmitted" : "billCancelled"),
    onError: () => setConfirm(null),
  });
  const reverse = useMutation({
    mutationFn: (reason: string) => unwrap(api.POST("/api/v1/purchasing/bills/{bill_id}/reverse", { params: { path: { bill_id: billId } }, body: { reason } })),
    onSuccess: () => done("billReversed"), onError: () => setReversing(false),
  });
  const reversePayment = useMutation({
    mutationFn: (v: { payment_id: string; reason: string }) => unwrap(api.POST("/api/v1/purchasing/bills/{bill_id}/reverse-payment", { params: { path: { bill_id: billId } }, body: v })),
    onSuccess: () => done("paymentReversed"), onError: () => setReversingPayment(null),
  });

  if (bill.error) return <ErrorState title={t("billNotFound")} message={bill.error.message} onRetry={() => void bill.refetch()} />;
  if (!b) return <Skeleton className="h-40 w-full" />;
  const due = amountDue(b);
  const open = isOpenBill(b.status);
  const exception = b.status === "pending_approval" && b.match_status === "exception";

  return (
    <>
      <PageHeader back={{ to: "/bills", label: t("bills") }} title={t("billTitle", { number: b.number })}
        description={<span className="flex flex-wrap items-center gap-2"><Status status={b.status} />{b.match_status !== "pending" && <Status status={b.match_status} />}<SupplierName id={b.supplier_id} link /></span>}
        actions={<>
          {canBill && b.status === "draft" && <Link to={`/bills/${b.id}/edit`}><Button variant="secondary"><Pencil className="h-4 w-4" />{t("edit")}</Button></Link>}
          {canBill && b.status === "draft" && <Button onClick={() => setConfirm("submit")}>{t("submitAndMatch")}</Button>}
          {canPay && open && <Button onClick={() => setPaying(true)}><Banknote className="h-4 w-4" />{t("pay")}</Button>}
          {canPay && owedBack && Number(owedBack) > 0 && <Button onClick={() => setRefunding(true)}>{t("recordRefundShort")}</Button>}
          <Menu label={t("moreActions")} trigger={<span className="inline-flex h-9 items-center rounded-lg border border-line bg-surface px-3 text-sm shadow-card">{t("more")}</span>} items={[
            { label: t("print"), icon: <Printer className="h-4 w-4" />, onSelect: () => window.print() },
            ...(canApprove && open ? [{ label: t("recordCreditShort"), icon: <FilePlus2 className="h-4 w-4" />, onSelect: () => setCrediting(true) }] : []),
            ...(canApprove && posted ? [{ label: t("reverseBill"), icon: <Undo2 className="h-4 w-4" />, danger: true, onSelect: () => setReversing(true) }] : []),
            ...(canBill && ["draft", "pending_approval"].includes(b.status) ? [{ label: t("cancelBill"), danger: true, onSelect: () => setConfirm("cancel") }] : []),
          ]} />
        </>} />
      {b.status === "pending_approval" && !exception && <ApprovalBar docType="supplier_bill" docId={b.id} waiting />}
      {exception && <ExceptionPanel billId={b.id} notes={b.match_notes} canDecide={canApprove} />}
      {b.status === "reversed" && <Alert tone="bad" className="mb-4">{t("reversedBecause", { reason: b.reverse_reason ?? "" })}</Alert>}
      {b.status === "draft" && <Alert tone="info" className="mb-4">{t("draftBillHint")}</Alert>}
      {b.match_notes.length > 0 && !exception && <Alert tone="warn" className="mb-4"><ul className="list-disc pl-5">{b.match_notes.map((n) => <li key={n}>{n}</li>)}</ul></Alert>}
      {open && isOverdue(b, today()) && <Alert tone="warn" className="mb-4">{t("overdueBy", { date: formatDate(b.due_date) })}</Alert>}
      {owedBack && Number(owedBack) > 0 && <Alert tone="info" className="mb-4">{t("supplierOwesYou", { amount: money(owedBack, currency) })}</Alert>}

      <div className="space-y-4">
        <Card>
          <DetailList items={[
            { label: t("supplier"), value: <SupplierName id={b.supplier_id} link /> },
            { label: t("theirInvoice"), value: b.supplier_invoice_no },
            { label: t("billDate"), value: formatDate(b.bill_date) },
            { label: t("dueDate"), value: formatDate(b.due_date) },
            { label: t("paid"), value: <Money value={b.amount_paid} companyId={b.company_id} /> },
            { label: t("credited"), value: <Money value={b.credited} companyId={b.company_id} /> },
            { label: t("refunded"), value: <Money value={b.refunded} companyId={b.company_id} /> },
            { label: t("stillOwed"), value: open || b.status === "paid" ? <span className="font-semibold"><Money value={due} companyId={b.company_id} /></span> : "—" },
          ]} />
        </Card>
        <Card title={t("lines")} flush>
          <DataTable rows={b.lines} rowKey={(l) => l.id} empty={{ title: t("noLines") }}
            columns={[
              { header: t("description"), cell: (l) => <LineName line={l} /> },
              { header: t("quantity"), align: "right", cell: (l) => quantity(l.quantity) },
              { header: t("unitCostBeforeTax"), align: "right", hideBelow: "sm", cell: (l) => <Money value={l.unit_cost} companyId={b.company_id} /> },
              { header: t("tax"), align: "right", hideBelow: "md", cell: (l) => <Money value={l.tax_amount} companyId={b.company_id} /> },
              { header: t("lineTotal"), align: "right", cell: (l) => <Money value={l.line_total} companyId={b.company_id} /> },
            ]} />
          <div className="border-t border-line p-4"><Totals subtotal={b.subtotal} tax={b.tax_total} total={b.total} currency={currency} /></div>
        </Card>
        {posted && (
          <Card title={t("paymentsMade")} flush>
            <DataTable rows={payments.data} loading={payments.isLoading} error={payments.error?.message} onRetry={() => void payments.refetch()} rowKey={(p) => p.payment_id} empty={{ title: t("noPayments") }}
              columns={[
                { header: t("number"), cell: (p) => <span className="font-mono text-xs">{p.number}</span> },
                { header: t("date"), cell: (p) => formatDate(p.business_date) },
                { header: t("method"), hideBelow: "sm", cell: (p) => t(`methods.${p.method}`, p.method) },
                { header: t("reference"), hideBelow: "md", cell: (p) => p.reference ?? "—" },
                { header: t("amount"), align: "right", cell: (p) => <Money value={p.amount} companyId={b.company_id} /> },
                { header: t("status"), cell: (p) => <Status status={p.status} /> },
                { header: "", align: "right", cell: (p) => canPay && p.status !== "reversed" && <Button size="sm" variant="ghost" onClick={() => setReversingPayment(p.payment_id)}>{t("reversePayment")}</Button> },
              ]} />
          </Card>
        )}
        {posted && (credits.data?.length ?? 0) > 0 && (
          <Card title={t("creditNotes")} flush>
            <DataTable rows={credits.data} rowKey={(c) => c.id} rowHref={(c) => `/credit-notes/${c.id}`} empty={{ title: t("noCreditNotes") }}
              columns={[
                { header: t("number"), cell: (c) => <span className="font-mono text-xs">{c.number}</span> },
                { header: t("theirCreditNo"), cell: (c) => c.supplier_credit_no },
                { header: t("date"), cell: (c) => formatDate(c.credit_date) },
                { header: t("total"), align: "right", cell: (c) => <Money value={c.total} companyId={c.company_id} /> },
              ]} />
          </Card>
        )}
      </div>

      <ConfirmDialog open={confirm !== null} onClose={() => setConfirm(null)} busy={run.isPending} danger={confirm === "cancel"}
        title={confirm ? t(`billConfirm.${confirm}.title`) : ""} message={confirm ? t(`billConfirm.${confirm}.message`, { number: b.number }) : ""}
        confirmLabel={confirm ? t(`billConfirm.${confirm}.button`) : ""} onConfirm={() => confirm && run.mutate(confirm)} />
      {reversing && <ReasonDialog open onClose={() => setReversing(false)} title={t("reverseBill")} message={t("reverseBillHint")} confirmLabel={t("reverseBill")} busy={reverse.isPending} onSubmit={(r) => reverse.mutate(r)} />}
      {reversingPayment && <ReasonDialog open onClose={() => setReversingPayment(null)} title={t("reversePayment")} message={t("reversePaymentHint")} confirmLabel={t("reversePayment")} busy={reversePayment.isPending}
        onSubmit={(reason) => reversePayment.mutate({ payment_id: reversingPayment, reason })} />}
      {paying && <SettleDrawer open onClose={() => setPaying(false)} kind="pay" bill={b} defaultAmount={due} />}
      {refunding && owedBack && <SettleDrawer open onClose={() => setRefunding(false)} kind="refund" bill={b} defaultAmount={owedBack} />}
      {crediting && <CreditNoteDrawer bill={b} onClose={() => setCrediting(false)} />}
    </>
  );
}

function LineName({ line }: { line: Bill["lines"][number] }) {
  const { t } = useTranslation("purchasing");
  if (line.product_id) return <ProductName id={line.product_id} />;
  return <>{line.description ?? (line.landed_receipt_id ? t("landedCharge") : "—")}</>;
}
