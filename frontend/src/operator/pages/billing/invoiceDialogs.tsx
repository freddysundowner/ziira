import { useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { Alert, Button, Checkbox, Field, FormGrid, Input, Modal, money, NumberInput, type Schemas, Select, Textarea, toast, today, useTranslation } from "@/sdk";

import type { PlatformSchema } from "../../types";
import { opApi, opUnwrap } from "../../client";
import { emptyLine, type InvoiceDraft, invoiceProblems, lineAmount, type LineDraft, previewSubtotal, toInvoiceIn } from "../../helpers/invoice";
import { useChange } from "../../stepUp";

type Invoice = PlatformSchema<"InvoiceOut">;

/** After any change to billing, whatever is on screen asks again (lists, the subscriber, the dashboard figures). */
export function useRefreshOperator() {
  const queryClient = useQueryClient();
  return () => void queryClient.invalidateQueries({ queryKey: ["operator"] });
}

export const invoiceTarget = (i: Invoice): string => i.tenant_name ?? i.tenant_code ?? String((i.bill_to as { name?: string }).name ?? "-");

/** Record money received against an invoice that still has a balance. */
export function RecordPaymentDialog({ invoices, initialId, onClose, onDone }: { invoices: Invoice[]; initialId?: string; onClose: () => void; onDone?: (invoice: Schemas["InvoiceDetail"]) => void }) {
  const { t } = useTranslation("operator");
  const refresh = useRefreshOperator();
  const [invoiceId, setInvoiceId] = useState(initialId ?? invoices[0]?.id ?? "");
  const invoice = invoices.find((i) => i.id === invoiceId);
  const [method, setMethod] = useState("");
  const [amount, setAmount] = useState(invoice?.balance ?? "");
  const [reference, setReference] = useState("");
  const [paidOn, setPaidOn] = useState(today());
  const [problem, setProblem] = useState<string | null>(null);

  const record = useChange(
    () => opUnwrap(opApi.POST("/api/v1/operator/invoices/{invoice_id}/payments", {
      params: { path: { invoice_id: invoiceId } }, body: { method: method.trim(), amount: amount.trim(), reference: reference.trim(), paid_on: paidOn || null },
    })),
    {
      onSuccess: (result) => { toast(t("billing.payment.recorded"), "ok"); refresh(); onDone?.(result); onClose(); },
      onError: (error) => setProblem(error.message),
    },
  );
  const ready = !!invoice && method.trim() !== "" && Number(amount) > 0;
  return (
    <Modal open onClose={onClose} title={t("billing.payment.title")} size="sm"
      footer={<>
        <Button variant="secondary" onClick={onClose}>{t("cancel")}</Button>
        <Button type="submit" form="payment-form" loading={record.isPending} disabled={!ready}>{t("billing.payment.record")}</Button>
      </>}>
      <form id="payment-form" className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (ready && !record.isPending) { setProblem(null); record.mutate(undefined); } }}>
        {invoices.length === 0 && <Alert tone="info">{t("billing.payment.nothingOpen")}</Alert>}
        <Field label={t("billing.payment.invoice")} required>
          <Select value={invoiceId} onChange={(e) => { setInvoiceId(e.target.value); setAmount(invoices.find((i) => i.id === e.target.value)?.balance ?? ""); }}>
            {invoices.map((i) => <option key={i.id} value={i.id}>{i.number ?? "-"} · {invoiceTarget(i)} · {money(i.balance, i.currency)}</option>)}
          </Select>
        </Field>
        <Field label={t("billing.payment.method")} hint={t("billing.payment.methodHint")} required>
          <Input value={method} onChange={(e) => setMethod(e.target.value)} list="payment-methods" maxLength={60} />
          <datalist id="payment-methods">{["bank", "cash", "mobile", "cheque", "card"].map((m) => <option key={m} value={t(`billing.payment.methods.${m}`)} />)}</datalist>
        </Field>
        <FormGrid>
          <Field label={invoice ? t("billing.payment.amountIn", { currency: invoice.currency }) : t("billing.payment.amount")} required><NumberInput value={amount} onChange={setAmount} /></Field>
          <Field label={t("billing.payment.paidOn")}><Input type="date" value={paidOn} onChange={(e) => setPaidOn(e.target.value)} /></Field>
        </FormGrid>
        <Field label={t("billing.payment.reference")}><Input value={reference} onChange={(e) => setReference(e.target.value)} maxLength={120} /></Field>
        {problem && <Alert tone="bad">{problem}</Alert>}
      </form>
    </Modal>
  );
}

/** A new draft invoice (or an issued one) for a subscriber or a licence customer, with its lines. */
export function InvoiceFormDialog({ tenantCode, licenceId, onClose }: { tenantCode?: string; licenceId?: string; onClose: () => void }) {
  const { t } = useTranslation("operator");
  const refresh = useRefreshOperator();
  const [draft, setDraft] = useState<InvoiceDraft>({ tenant_code: tenantCode ?? "", licence_id: licenceId ?? "", currency: "", lines: [emptyLine()], tax_inclusive: false, notes: "", due_date: "", issue: false });
  const [problem, setProblem] = useState<string | null>(null);
  const [showProblems, setShowProblems] = useState(false);
  const patch = (p: Partial<InvoiceDraft>) => setDraft((d) => ({ ...d, ...p }));
  const setLine = (i: number, p: Partial<LineDraft>) => setDraft((d) => ({ ...d, lines: d.lines.map((l, n) => (n === i ? { ...l, ...p } : l)) }));
  const problems = invoiceProblems(draft);

  const create = useChange(
    () => opUnwrap(opApi.POST("/api/v1/operator/invoices", { body: toInvoiceIn(draft) })),
    {
      onSuccess: (invoice) => { toast(t(draft.issue ? "billing.invoiceForm.issued" : "billing.invoiceForm.saved", { number: invoice.number ?? "" }), "ok"); refresh(); onClose(); },
      onError: (error) => setProblem(error.message),
    },
  );
  const submit = () => {
    setProblem(null);
    if (problems.length > 0) { setShowProblems(true); return; }
    create.mutate(undefined);
  };
  const fixed = !!tenantCode || !!licenceId;
  return (
    <Modal open onClose={onClose} title={t("billing.invoiceForm.title")} size="lg"
      footer={<>
        <Button variant="secondary" onClick={onClose}>{t("cancel")}</Button>
        <Button type="submit" form="invoice-form" loading={create.isPending}>{t(draft.issue ? "billing.invoiceForm.createIssue" : "billing.invoiceForm.createDraft")}</Button>
      </>}>
      <form id="invoice-form" className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (!create.isPending) submit(); }}>
        <FormGrid>
          {licenceId ? (
            <Field label={t("billing.invoiceForm.licence")}><Input value={licenceId} readOnly className="font-mono text-xs" /></Field>
          ) : (
            <Field label={t("billing.invoiceForm.subscriber")} hint={t("billing.invoiceForm.subscriberHint")} required>
              <Input value={draft.tenant_code} onChange={(e) => patch({ tenant_code: e.target.value })} readOnly={fixed} className="font-mono" autoComplete="off" />
            </Field>
          )}
          <Field label={t("billing.invoiceForm.currency")} hint={t("billing.invoiceForm.currencyHint")}>
            <Input value={draft.currency} onChange={(e) => patch({ currency: e.target.value.toUpperCase() })} maxLength={3} className="font-mono uppercase" />
          </Field>
        </FormGrid>

        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">{t("billing.invoiceForm.lines")}</legend>
          {draft.lines.map((line, i) => {
            const amount = lineAmount(line.quantity, line.unit_amount);
            return (
              <div key={i} className="grid grid-cols-[1fr_auto] gap-2 rounded-lg border border-line p-2 sm:grid-cols-[1fr_5rem_7rem_6rem_auto] sm:items-end">
                <Field label={t("billing.invoiceForm.description")} className="col-span-2 sm:col-span-1"><Input value={line.description} onChange={(e) => setLine(i, { description: e.target.value })} maxLength={300} /></Field>
                <Field label={t("billing.invoiceForm.quantity")}><NumberInput value={line.quantity} onChange={(v) => setLine(i, { quantity: v })} /></Field>
                <Field label={t("billing.invoiceForm.unitAmount")}>
                  <Input value={line.unit_amount} inputMode="decimal" className="tnum text-right" onChange={(e) => { const v = e.target.value.replace(/,/g, "."); if (/^-?\d*\.?\d*$/.test(v)) setLine(i, { unit_amount: v }); }} />
                </Field>
                <p className="tnum text-right text-sm text-muted sm:pb-2" aria-label={t("billing.invoiceForm.lineAmount")}>{amount ?? "-"}</p>
                <Button variant="ghost" size="sm" aria-label={t("billing.invoiceForm.removeLine")} disabled={draft.lines.length === 1} onClick={() => patch({ lines: draft.lines.filter((_, n) => n !== i) })}><Trash2 className="h-4 w-4" /></Button>
              </div>
            );
          })}
          <p className="text-xs text-muted">{t("billing.invoiceForm.discountHint")}</p>
          <div className="flex items-center justify-between">
            <Button size="sm" variant="secondary" onClick={() => patch({ lines: [...draft.lines, emptyLine()] })}><Plus className="h-4 w-4" /> {t("billing.invoiceForm.addLine")}</Button>
            <p className="text-sm text-muted">{t("billing.invoiceForm.preview")} <span className="tnum font-medium text-ink">{previewSubtotal(draft.lines)}</span></p>
          </div>
        </fieldset>

        <FormGrid>
          <Field label={t("billing.invoiceForm.dueDate")} hint={t("billing.invoiceForm.dueHint")}><Input type="date" value={draft.due_date} onChange={(e) => patch({ due_date: e.target.value })} /></Field>
          <div className="space-y-2 sm:pt-6">
            <Checkbox label={t("billing.invoiceForm.taxInclusive")} checked={draft.tax_inclusive} onChange={(e) => patch({ tax_inclusive: e.target.checked })} />
            <Checkbox label={t("billing.invoiceForm.issueNow")} checked={draft.issue} onChange={(e) => patch({ issue: e.target.checked })} />
          </div>
        </FormGrid>
        <Field label={t("billing.invoiceForm.notes")}><Textarea value={draft.notes} onChange={(e) => patch({ notes: e.target.value })} rows={2} maxLength={2000} /></Field>
        <p className="text-xs text-muted">{t("billing.invoiceForm.taxNote")}</p>
        {showProblems && problems.length > 0 && <Alert tone="bad"><ul className="list-disc pl-4">{problems.map((p) => <li key={p}>{t(`billing.invoiceForm.problems.${p}`)}</li>)}</ul></Alert>}
        {problem && <Alert tone="bad">{problem}</Alert>}
      </form>
    </Modal>
  );
}
