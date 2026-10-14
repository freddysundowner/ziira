import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api, Button, Drawer, Field, NumberInput, Select, Textarea, quantity, toast, unwrap, useMutation, useQueryClient, useTranslation } from "@/sdk";

import { useReasons } from "../hooks";
import { isPositive } from "../lib";
import type { Receipt } from "../types";
import { ProductName } from "./names";

/** Send received goods back to the supplier: pick the quantities, a reason, and the stock leaves at once. Mount only while open. */
export function ReturnDrawer({ receipt, onClose }: { receipt: Receipt; onClose: () => void }) {
  const { t } = useTranslation("purchasing");
  const qc = useQueryClient();
  const navigate = useNavigate();
  const reasons = useReasons("purchase_return");
  const [qty, setQty] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const chosen = receipt.lines.filter((l) => isPositive(qty[l.id] ?? ""));
  const reasonId = reason || reasons.data?.[0]?.id || "";

  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/purchasing/receipts/{receipt_id}/returns", { params: { path: { receipt_id: receipt.id } }, body: {
      lines: chosen.map((l) => ({ receipt_line_id: l.id, quantity: qty[l.id] ?? "0" })), reason_code_id: reasonId, note: note.trim() || null } })),
    onSuccess: (r) => { void qc.invalidateQueries({ queryKey: ["purchasing"] }); toast(t("returnSaved", { number: r.number }), "ok"); onClose(); navigate(`/returns/${r.id}`); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };

  return (
    <Drawer open onClose={onClose} title={t("returnGoods")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="return-form" variant="danger" loading={save.isPending} disabled={chosen.length === 0 || !reasonId}>{t("sendBack")}</Button></>}>
      <form id="return-form" onSubmit={submit} className="space-y-4">
        <p className="text-sm text-muted">{t("returnHint")}</p>
        <div className="space-y-2">
          {receipt.lines.map((l) => (
            <div key={l.id} className="grid grid-cols-[minmax(0,1fr)_7rem] items-end gap-3 rounded-lg border border-line p-3">
              <div className="text-sm"><ProductName id={l.product_id} /><p className="text-xs text-muted">{t("receivedQty", { qty: quantity(l.quantity) })}</p></div>
              <Field label={t("returnQty")}><NumberInput value={qty[l.id] ?? ""} onChange={(v) => setQty((q) => ({ ...q, [l.id]: v }))} /></Field>
            </div>
          ))}
        </div>
        <Field label={t("returnReason")} required>
          <Select value={reasonId} onChange={(e) => setReason(e.target.value)}>{reasons.data?.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}</Select>
        </Field>
        <Field label={t("note")}><Textarea value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} /></Field>
      </form>
    </Drawer>
  );
}
