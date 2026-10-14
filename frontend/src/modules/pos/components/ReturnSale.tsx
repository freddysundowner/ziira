import { type FormEvent, useState } from "react";

import {
  api, Alert, Button, Drawer, Field, NumberInput, orNull, quantity, Schemas, Select, Textarea, toast, unwrap, useFormState, useMutation, useQueryClient,
  useTranslation,
} from "@/sdk";

import { useLocations, useMoney, useReasons } from "../hooks";
import { chosenReturnLines, overReturned } from "../lib";

type Sale = Schemas["SaleOut"];

const METHODS = ["cash", "mobile_money", "exchange", "credit_note"] as const;

/** Takes goods back from a sale and refunds them. The server refunds each line from what it really sold for. */
export function ReturnSale({ sale, itemNames, open, onClose }: { sale: Sale; itemNames: string[]; open: boolean; onClose: () => void }) {
  const { t } = useTranslation("pos");
  const qc = useQueryClient();
  const m = useMoney();
  const reasons = useReasons("sale_return", open);
  const locations = useLocations(sale.branch_id, open);
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const f = useFormState({ reason_code_id: "", refund_method: "cash", note: "", restock_location_id: "" });
  const sold = Object.fromEntries(sale.lines.map((l) => [l.id, l.quantity]));
  const chosen = chosenReturnLines(quantities);
  const tooMany = overReturned(quantities, sold);
  const reason = reasons.data?.find((r) => r.id === f.values.reason_code_id);
  const methods = METHODS.filter((x) => x !== "credit_note" || sale.customer_id);

  const create = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/pos/sales/{sale_id}/returns", { params: { path: { sale_id: sale.id } }, body: {
      lines: chosen, reason_code_id: f.values.reason_code_id, refund_method: f.values.refund_method as (typeof METHODS)[number],
      note: orNull(f.values.note), restock_location_id: f.values.restock_location_id || null } })),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ["pos-sale", sale.id] });
      void qc.invalidateQueries({ queryKey: ["pos-returns"] });
      toast(r.status === "pending_approval" ? t("returnPending", { number: r.number }) : t("returnDone", { number: r.number, total: m(r.total, sale.company_id) }), "ok");
      setQuantities({}); f.reset(); onClose();
    },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); create.mutate(); };
  const blocked = chosen.length === 0 || tooMany.length > 0 || !f.values.reason_code_id || Boolean(reason?.requires_note && !f.values.note.trim());

  return (
    <Drawer open={open} onClose={onClose} title={t("returnTitle", { number: sale.number })}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="return-sale" loading={create.isPending} disabled={blocked}>{t("recordReturn")}</Button></>}>
      <form id="return-sale" onSubmit={submit} className="space-y-4">
        <p className="text-sm text-muted">{t("returnHint")}</p>
        <div className="divide-y divide-line rounded-lg border border-line">
          {sale.lines.map((l, i) => (
            <div key={l.id} className="flex items-center gap-3 p-3">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{itemNames[i] ?? t("itemNumber", { n: l.line_no })}</p>
                <p className="text-xs text-muted">{t("soldQuantity", { qty: quantity(l.quantity) })} · {m(l.line_total, sale.company_id)}</p>
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
        <Field label={t("refundMethod")} error={f.error("refund_method")}>
          <Select {...f.bind("refund_method")}>{methods.map((x) => <option key={x} value={x}>{t(`refundMethods.${x}`)}</option>)}</Select>
        </Field>
        {locations.data && locations.data.length > 0 && (
          <Field label={t("restockTo")} hint={t("restockHint")} error={f.error("restock_location_id")}>
            <Select {...f.bind("restock_location_id")}>
              <option value="">{t("defaultStore")}</option>
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
