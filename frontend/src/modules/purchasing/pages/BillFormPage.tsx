import { PackagePlus, Plus, Truck } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import {
  Alert, api, Button, Card, ErrorState, Field, FormGrid, Input, money, PageHeader, Select, Skeleton, toast, today, unwrap, useCompany, useCurrency, useMutation, useQuery,
  useQueryClient, useTranslation, useUnsavedWarning,
} from "@/sdk";

import { AddFromReceipt, type BillLineDraft, BillLineRow, blankBillLine, useSupplierReceipts } from "../components/BillLines";
import { useLines } from "../components/lines";
import { SupplierPicker } from "../components/pickers";
import { useSupplier } from "../hooks";
import { isPositive, previewSubtotal } from "../lib";

/** Capture a supplier's invoice as a draft (or edit a draft). Submitting it from the bill's page runs the three-way match. */
export default function BillFormPage() {
  const { t } = useTranslation("purchasing");
  const { billId } = useParams();
  const [params] = useSearchParams();
  const receiptId = params.get("receipt");
  const bill = useQuery({ enabled: !!billId, queryKey: ["purchasing", "bill", billId], queryFn: () => unwrap(api.GET("/api/v1/purchasing/bills/{bill_id}", { params: { path: { bill_id: billId ?? "" } } })) });
  const receipt = useQuery({ enabled: !!receiptId, queryKey: ["purchasing", "receipt", receiptId], queryFn: () => unwrap(api.GET("/api/v1/purchasing/receipts/{receipt_id}", { params: { path: { receipt_id: receiptId ?? "" } } })) });
  const failed = bill.error ?? receipt.error;
  if (failed) return <ErrorState title={t("billNotFound")} message={failed.message} onRetry={() => { void bill.refetch(); void receipt.refetch(); }} />;
  if ((billId && !bill.data) || (receiptId && !receipt.data)) return <Skeleton className="h-60 w-full" />;
  const initial: BillLineDraft[] = bill.data
    ? bill.data.lines.map((l) => ({
        key: l.id, kind: l.landed_receipt_id ? "landed" : l.receipt_line_id ? "goods" : "expense", receipt_line_id: l.receipt_line_id ?? "", landed_receipt_id: l.landed_receipt_id ?? "",
        product_id: l.product_id ?? "", expense_account_id: l.expense_account_id ?? "", tax_code_id: "", description: l.description ?? "", quantity: l.quantity, unit_cost: l.unit_cost }))
    : receipt.data?.lines.map((l) => ({ ...blankBillLine("goods"), key: l.id, receipt_line_id: l.id, product_id: l.product_id, quantity: l.quantity, unit_cost: l.unit_cost })) ?? [];
  return <BillForm key={bill.data?.id ?? "new"} existing={bill.data} initialLines={initial} initialSupplier={receipt.data?.supplier_id ?? params.get("supplier") ?? ""} />;
}

function BillForm({ existing, initialLines, initialSupplier }: {
  existing?: { id: string; number: string; company_id: string; supplier_id: string; supplier_invoice_no: string; bill_date: string; due_date: string; status: string };
  initialLines: BillLineDraft[]; initialSupplier: string;
}) {
  const { t } = useTranslation("purchasing");
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { company } = useCompany();
  const [supplierId, setSupplierId] = useState(existing?.supplier_id ?? initialSupplier);
  const [invoiceNo, setInvoiceNo] = useState(existing?.supplier_invoice_no ?? "");
  const [billDate, setBillDate] = useState(existing?.bill_date ?? today());
  const [dueDate, setDueDate] = useState(existing?.due_date ?? "");
  const [authorityRef, setAuthorityRef] = useState("");
  const [adding, setAdding] = useState(false);
  const [touched, setTouched] = useState(false);
  useUnsavedWarning(touched);
  const supplier = useSupplier(supplierId || null);
  const companyId = existing?.company_id ?? supplier.data?.company_id ?? company?.id;
  const currency = useCurrency(companyId);
  const receipts = useSupplierReceipts(supplierId);
  const { lines, add, update, remove } = useLines<BillLineDraft>(() => blankBillLine("expense"), initialLines);
  const change = (fn: () => void) => { setTouched(true); fn(); };

  const valid = !!supplierId && !!invoiceNo.trim() && lines.length > 0 && lines.every((l) => isPositive(l.quantity) && l.unit_cost !== "" && (l.kind !== "expense" || !!l.description.trim() || !!l.expense_account_id));
  const payload = lines.map((l) => ({
    quantity: l.quantity, unit_cost: l.unit_cost, receipt_line_id: l.receipt_line_id || null, landed_receipt_id: l.landed_receipt_id || null,
    expense_account_id: l.expense_account_id || null, description: l.description.trim() || null, tax_code_id: l.tax_code_id || null }));
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => existing
      ? unwrap(api.PUT("/api/v1/purchasing/bills/{bill_id}", { params: { path: { bill_id: existing.id } }, body: { due_date: dueDate || null, lines: payload } }))
      : unwrap(api.POST("/api/v1/purchasing/bills", { body: { supplier_id: supplierId, supplier_invoice_no: invoiceNo.trim(), bill_date: billDate, due_date: dueDate || null, authority_ref: authorityRef.trim() || null, lines: payload } })),
    onSuccess: (b) => { setTouched(false); void qc.invalidateQueries({ queryKey: ["purchasing"] }); toast(t("billSaved", { number: b.number }), "ok"); navigate(`/bills/${b.id}`); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  const receiptNumber = (id: string) => receipts.data?.find((r) => r.id === id)?.number ?? "…";
  const addCharge = () => change(() => add({ kind: "landed", quantity: "1", landed_receipt_id: receipts.data?.[0]?.id ?? "" }));

  return (
    <form onSubmit={submit}>
      <PageHeader back={{ to: existing ? `/bills/${existing.id}` : "/bills", label: existing ? existing.number : t("bills") }} title={existing ? t("editBill", { number: existing.number }) : t("newBill")} description={t("billFormHint")}
        actions={<Button type="submit" loading={save.isPending} disabled={!valid}>{t("saveDraft")}</Button>} />
      <div className="space-y-4">
        <Card title={t("billDetails")}>
          <FormGrid cols={3}>
            <Field label={t("supplier")} required><SupplierPicker value={supplierId} onChange={(v) => change(() => { setSupplierId(v); })} disabled={!!existing} /></Field>
            <Field label={t("theirInvoice")} required hint={t("theirInvoiceHint")}><Input value={invoiceNo} maxLength={60} disabled={!!existing} onChange={(e) => change(() => setInvoiceNo(e.target.value))} /></Field>
            <Field label={t("billDate")} required><Input type="date" max={today()} value={billDate} disabled={!!existing} onChange={(e) => change(() => setBillDate(e.target.value))} /></Field>
            <Field label={t("dueDate")} hint={t("dueDateHint")}><Input type="date" min={billDate} value={dueDate} onChange={(e) => change(() => setDueDate(e.target.value))} /></Field>
            {!existing && <Field label={t("authorityRef")} hint={t("authorityRefHint")}><Input value={authorityRef} maxLength={60} onChange={(e) => change(() => setAuthorityRef(e.target.value))} /></Field>}
          </FormGrid>
        </Card>
        <Card title={t("lines")} description={t("costsBeforeTax")}
          actions={<>
            <Button size="sm" variant="secondary" disabled={!supplierId} onClick={() => setAdding(true)}><PackagePlus className="h-4 w-4" />{t("addFromReceipt")}</Button>
            <Button size="sm" variant="secondary" disabled={!supplierId || (receipts.data?.length ?? 0) === 0} onClick={addCharge}><Truck className="h-4 w-4" />{t("addLanded")}</Button>
            <Button size="sm" variant="secondary" onClick={() => change(() => add())}><Plus className="h-4 w-4" />{t("addOtherCharge")}</Button>
          </>}>
          {!supplierId && <Alert tone="info" className="mb-3">{t("pickSupplierFirst")}</Alert>}
          {supplierId && lines.length === 0 && <Alert tone="info" className="mb-3">{t("billLinesHint")}</Alert>}
          <div className="space-y-2">
            {lines.map((l) => (
              <div key={l.key}>
                {l.kind === "landed" && (
                  <Field label={t("landedReceipt")} className="mb-2">
                    <Select value={l.landed_receipt_id}
                      onChange={(e) => change(() => update(l.key, { landed_receipt_id: e.target.value }))}>
                      {receipts.data?.map((r) => <option key={r.id} value={r.id}>{r.number}</option>)}
                    </Select>
                  </Field>
                )}
                <BillLineRow line={l} companyId={companyId} receiptNumber={receiptNumber} onChange={(p) => change(() => update(l.key, p))} onRemove={() => change(() => remove(l.key))} />
              </div>
            ))}
          </div>
          <p className="mt-4 text-right text-sm text-muted">{t("previewSubtotal")}: <span className="tnum font-medium text-ink">{money(previewSubtotal(lines), currency)}</span> <span className="text-xs">({t("previewNote")})</span></p>
        </Card>
      </div>
      {adding && <AddFromReceipt supplierId={supplierId} onClose={() => setAdding(false)} onAdd={(ls) => change(() => ls.forEach((x) => add(x)))} />}
    </form>
  );
}
