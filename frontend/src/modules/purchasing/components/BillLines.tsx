import { Trash2 } from "lucide-react";
import { useState } from "react";

import { api, Button, Field, formatDate, IconButton, Input, Modal, NumberInput, quantity, Select, unwrap, useQuery, useTranslation } from "@/sdk";

import { useExpenseAccounts, useTaxCodes } from "../hooks";
import { LINE_ROW } from "./lines";
import { ProductName } from "./names";

export interface BillLineDraft {
  key: string; kind: "goods" | "landed" | "expense"; receipt_line_id: string; landed_receipt_id: string; product_id: string;
  expense_account_id: string; tax_code_id: string; description: string; quantity: string; unit_cost: string;
}
export const blankBillLine = (kind: BillLineDraft["kind"]): Omit<BillLineDraft, "key"> => ({
  kind, receipt_line_id: "", landed_receipt_id: "", product_id: "", expense_account_id: "", tax_code_id: "", description: "", quantity: "1", unit_cost: "",
});

/** The supplier's recent receipts, used for choosing goods to bill and for transport or duty charges. */
export function useSupplierReceipts(supplierId: string) {
  return useQuery({
    enabled: !!supplierId, queryKey: ["purchasing", "receipts", { supplier: supplierId }],
    queryFn: () => unwrap(api.GET("/api/v1/purchasing/receipts", { params: { query: { supplier_id: supplierId, limit: 100 } } })),
  });
}

/** One bill line: goods taken from a receipt, a transport or duty charge on a receipt, or any other charge. */
export function BillLineRow({ line, companyId, receiptNumber, onChange, onRemove }: {
  line: BillLineDraft; companyId?: string; receiptNumber: (id: string) => string; onChange: (patch: Partial<BillLineDraft>) => void; onRemove: () => void;
}) {
  const { t } = useTranslation("purchasing");
  const accounts = useExpenseAccounts(line.kind === "expense" ? companyId : undefined);
  const taxes = useTaxCodes();
  return (
    <div className={`${LINE_ROW} md:grid-cols-[minmax(0,1fr)_7rem_9rem_2.25rem]`}>
      {line.kind === "goods" && <div><p className="text-xs font-medium uppercase tracking-wide text-muted">{t("goods")}</p><p className="text-sm"><ProductName id={line.product_id} /></p></div>}
      {line.kind === "landed" && <div><p className="text-xs font-medium uppercase tracking-wide text-muted">{t("landedCharge")}</p><p className="text-sm">{t("landedFor", { number: receiptNumber(line.landed_receipt_id) })}</p></div>}
      {line.kind === "expense" && (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("description")}><Input value={line.description} maxLength={200} onChange={(e) => onChange({ description: e.target.value })} /></Field>
          {(accounts.data?.length ?? 0) > 0 && (
            <Field label={t("expenseAccount")}>
              <Select value={line.expense_account_id} onChange={(e) => onChange({ expense_account_id: e.target.value })}>
                <option value="">{t("choose")}</option>{accounts.data?.map((a) => <option key={a.id} value={a.id}>{a.code} · {a.name}</option>)}
              </Select>
            </Field>
          )}
          {(taxes.data?.length ?? 0) > 0 && (
            <Field label={t("taxCode")}>
              <Select value={line.tax_code_id} onChange={(e) => onChange({ tax_code_id: e.target.value })}>
                <option value="">{t("defaultTax")}</option>{taxes.data?.map((x) => <option key={x.id} value={x.id}>{x.code} · {x.name}</option>)}
              </Select>
            </Field>
          )}
        </div>
      )}
      <Field label={t("quantity")}><NumberInput value={line.quantity} disabled={line.kind === "landed"} onChange={(v) => onChange({ quantity: v })} /></Field>
      <Field label={t("unitCostBeforeTax")}><NumberInput value={line.unit_cost} onChange={(v) => onChange({ unit_cost: v })} /></Field>
      <IconButton label={t("removeLine")} className="justify-self-end" onClick={onRemove}><Trash2 className="h-4 w-4" /></IconButton>
    </div>
  );
}

/** Pick goods from one of the supplier's receipts to bill. */
export function AddFromReceipt({ supplierId, onAdd, onClose }: { supplierId: string; onAdd: (lines: Partial<BillLineDraft>[]) => void; onClose: () => void }) {
  const { t } = useTranslation("purchasing");
  const receipts = useSupplierReceipts(supplierId);
  const [receiptId, setReceiptId] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const id = receiptId || receipts.data?.[0]?.id || "";
  const receipt = useQuery({ enabled: !!id, queryKey: ["purchasing", "receipt", id], queryFn: () => unwrap(api.GET("/api/v1/purchasing/receipts/{receipt_id}", { params: { path: { receipt_id: id } } })) });
  const lines = receipt.data?.lines ?? [];

  return (
    <Modal open onClose={onClose} title={t("addFromReceipt")} size="md"
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button>
        <Button disabled={picked.size === 0} onClick={() => { onAdd(lines.filter((l) => picked.has(l.id)).map((l) => ({ kind: "goods", receipt_line_id: l.id, product_id: l.product_id, quantity: l.quantity, unit_cost: l.unit_cost }))); onClose(); }}>{t("addSelected")}</Button></>}>
      <div className="space-y-3">
        {receipts.data?.length === 0 && <p className="text-sm text-muted">{t("noSupplierReceipts")}</p>}
        {(receipts.data?.length ?? 0) > 0 && (
          <Field label={t("receipt")}>
            <Select value={id} onChange={(e) => { setReceiptId(e.target.value); setPicked(new Set()); }}>
              {receipts.data?.map((r) => <option key={r.id} value={r.id}>{r.number} · {formatDate(r.received_at)}{r.delivery_note_no ? ` · ${r.delivery_note_no}` : ""}</option>)}
            </Select>
          </Field>
        )}
        {receipt.error && <p className="text-sm text-bad">{receipt.error.message}</p>}
        <ul className="divide-y divide-line rounded-lg border border-line">
          {lines.map((l) => (
            <li key={l.id}>
              <label className="flex cursor-pointer items-center gap-3 px-3 py-2.5 text-sm">
                <input type="checkbox" className="h-4 w-4 accent-[rgb(var(--brand))]" checked={picked.has(l.id)}
                  onChange={(e) => setPicked((p) => { const n = new Set(p); if (e.target.checked) n.add(l.id); else n.delete(l.id); return n; })} />
                <span className="min-w-0 flex-1"><ProductName id={l.product_id} /></span>
                <span className="tnum text-muted">{quantity(l.quantity)}</span>
              </label>
            </li>
          ))}
        </ul>
        <p className="text-xs text-muted">{t("billedAlreadyNote")}</p>
      </div>
    </Modal>
  );
}
