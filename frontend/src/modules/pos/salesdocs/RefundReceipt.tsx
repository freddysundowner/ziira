import { type FormEvent, useEffect } from "react";

import {
  api, Alert, Button, Drawer, Field, FormGrid, Input, NumberInput, orNull, Schemas, Select, Textarea, toast, unwrap, useFormState, useMutation, useQueryClient, useTranslation,
} from "@/sdk";

import { useMoney } from "../hooks";

type Receipt = Schemas["ziira__modules__pos__api__schemas__ReceiptSummaryOut"];
const METHODS = ["cash", "mobile_money", "bank"] as const;

/** Gives back money a customer paid in advance and has not used. The server refuses more than is held on their account. */
export function RefundReceipt({ receipt, open, onClose }: { receipt: Receipt; open: boolean; onClose: () => void }) {
  const { t } = useTranslation("pos");
  const qc = useQueryClient();
  const m = useMoney();
  const f = useFormState({ amount: receipt.unallocated, method: "cash", reason: "", external_ref: "" });
  const { reset } = f;
  useEffect(() => { if (open) { reset(); f.set("amount", receipt.unallocated); } }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const create = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/pos/receipts/{receipt_id}/refund", { params: { path: { receipt_id: receipt.id } }, body: {
      amount: f.values.amount, method: f.values.method as (typeof METHODS)[number], reason: f.values.reason.trim(), external_ref: orNull(f.values.external_ref) } })),
    onSuccess: (r) => {
      for (const key of ["pos-receipt", "pos-docs", "customer-balance", "customer-statement", "customer-receipts"]) void qc.invalidateQueries({ queryKey: [key] });
      toast(t("docs.refundDone", { number: r.number, amount: m(r.amount, receipt.company_id) }), "ok");
      onClose();
    },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); create.mutate(); };

  return (
    <Drawer open={open} onClose={onClose} title={t("docs.refundTitle", { number: receipt.number })}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="refund-receipt" loading={create.isPending} disabled={!f.values.amount || !f.values.reason.trim()}>{t("docs.giveBack")}</Button></>}>
      <form id="refund-receipt" onSubmit={submit} className="space-y-4">
        <p className="text-sm text-muted">{t("docs.refundHint", { held: m(receipt.unallocated, receipt.company_id) })}</p>
        <FormGrid>
          <Field label={t("amount")} required error={f.error("amount")}><NumberInput value={f.values.amount} onChange={(v) => f.set("amount", v)} /></Field>
          <Field label={t("method")} error={f.error("method")}>
            <Select {...f.bind("method")}>{METHODS.map((x) => <option key={x} value={x}>{t(`docs.refundVia.${x}`)}</option>)}</Select>
          </Field>
        </FormGrid>
        {f.values.method !== "cash" && <Field label={t("reference")} error={f.error("external_ref")}><Input {...f.bind("external_ref")} maxLength={60} /></Field>}
        <Field label={t("reason")} required error={f.error("reason")}><Textarea rows={2} maxLength={300} {...f.bind("reason")} /></Field>
        {f.values.method === "cash" && <Alert tone="info">{t("docs.cashRefundNote")}</Alert>}
      </form>
    </Drawer>
  );
}
