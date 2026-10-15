import { type FormEvent, useState } from "react";

import {
  api, Alert, Button, Drawer, Field, NumberInput, orNull, quantity, Schemas, Select, Textarea, toast, unwrap, useFormState, useMutation, useQueryClient, useTranslation,
} from "@/sdk";

import { useLocations, useMoney, useReasons } from "../hooks";
import { chosenReturnLines, overReturned } from "../lib";
import { ProductName } from "./hooks";
import { returnMethods } from "./lib";

type Invoice = Schemas["InvoiceOut"];
/** Takes goods back from an invoice: a credit note while it is unpaid, a refund once it is paid (the server decides which and refuses more than was sold). */
export function InvoiceReturn({ invoice, open, onClose }: { invoice: Invoice; open: boolean; onClose: () => void }) {
  const { t } = useTranslation("pos");
  const qc = useQueryClient();
  const m = useMoney();
  const reasons = useReasons("sale_return", open);
  const locations = useLocations(invoice.branch_id, open);
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const methods = returnMethods(invoice);
  const owing = methods[0] === "credit_note";
  const f = useFormState({ reason_code_id: "", refund_method: methods[0], note: "", restock_location_id: "" });
  const sold = Object.fromEntries(invoice.lines.map((l) => [l.id, l.quantity]));
  const chosen = chosenReturnLines(quantities);
  const tooMany = overReturned(quantities, sold);
  const reason = reasons.data?.find((r) => r.id === f.values.reason_code_id);

  const create = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/pos/invoices/{invoice_id}/returns", { params: { path: { invoice_id: invoice.id } }, body: {
      lines: chosen.map((l) => ({ invoice_line_id: l.sale_line_id, quantity: l.quantity })), reason_code_id: f.values.reason_code_id,
      refund_method: f.values.refund_method as (typeof methods)[number], note: orNull(f.values.note), restock_location_id: f.values.restock_location_id || null } })),
    onSuccess: (r) => {
      for (const key of ["pos-invoice", "pos-docs", "pos-returns", "customer-balance", "customer-statement", "customer-invoices"]) void qc.invalidateQueries({ queryKey: [key] });
      toast(r.status === "pending_approval" ? t("returnPending", { number: r.number }) : t("returnDone", { number: r.number, total: m(r.total, invoice.company_id) }), "ok");
      setQuantities({}); f.reset(); onClose();
    },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); create.mutate(); };
  const blocked = chosen.length === 0 || tooMany.length > 0 || !f.values.reason_code_id || Boolean(reason?.requires_note && !f.values.note.trim());

  return (
    <Drawer open={open} onClose={onClose} title={t("returnTitle", { number: invoice.number })}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="return-invoice" loading={create.isPending} disabled={blocked}>{t("recordReturn")}</Button></>}>
      <form id="return-invoice" onSubmit={submit} className="space-y-4">
        <p className="text-sm text-muted">{t("returnHint")}</p>
        <div className="divide-y divide-line rounded-lg border border-line">
          {invoice.lines.map((l) => (
            <div key={l.id} className="flex items-center gap-3 p-3">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm"><ProductName id={l.product_id} /></p>
                <p className="text-xs text-muted">{t("soldQuantity", { qty: quantity(l.quantity) })} · {m(l.line_total, invoice.company_id)}</p>
              </div>
              <Field label={t("returnQuantity")} error={tooMany.includes(l.id) ? t("moreThanSold") : null} className="w-28">
                <NumberInput value={quantities[l.id] ?? ""} placeholder="0" invalid={tooMany.includes(l.id)} onChange={(v) => setQuantities((q) => ({ ...q, [l.id]: v }))} />
              </Field>
            </div>
          ))}
        </div>
        <Field label={t("reason")} required error={f.error("reason_code_id")}>
          <Select {...f.bind("reason_code_id")} required>
            <option value="">{t("choose")}</option>
            {(reasons.data ?? []).map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
          </Select>
        </Field>
        <Field label={t("refundMethod")} hint={t(owing ? "docs.returnUnpaidHint" : "docs.returnPaidHint")} error={f.error("refund_method")}>
          <Select {...f.bind("refund_method")}>{methods.map((x) => <option key={x} value={x}>{t(`refundMethods.${x}`)}</option>)}</Select>
        </Field>
        {locations.data && locations.data.length > 0 && (
          <Field label={t("restockTo")} hint={t("restockHint")} error={f.error("restock_location_id")}>
            <Select {...f.bind("restock_location_id")}>
              <option value="">{t("docs.restockDefault")}</option>
              {locations.data.filter((x) => x.is_active).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
            </Select>
          </Field>
        )}
        <Field label={t("note")} required={reason?.requires_note} error={f.error("note")}><Textarea rows={2} maxLength={500} {...f.bind("note")} /></Field>
        <Alert tone="info">{t("returnApprovalHint")}</Alert>
      </form>
    </Drawer>
  );
}
