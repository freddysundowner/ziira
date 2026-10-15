import { type FormEvent } from "react";

import { api, Button, Drawer, Field, FormGrid, Input, NumberInput, Select, toast, today, unwrap, useFormState, useMutation, useQueryClient, useTranslation } from "@/sdk";

import { PayFrom, usePayFromAccounts } from "./PayFrom";
import { PAY_METHODS } from "../lib";
import type { PayMethod } from "../types";

/** Mount it only while open (state starts fresh each time). Pay a supplier bill (kind "pay") or record money a supplier paid back (kind "refund"): same fields, different endpoint. */
export function SettleDrawer({ open, onClose, kind, bill, defaultAmount }: {
  open: boolean; onClose: () => void; kind: "pay" | "refund"; bill: { id: string; number: string; company_id: string }; defaultAmount: string;
}) {
  const { t } = useTranslation("purchasing");
  const qc = useQueryClient();
  const f = useFormState({ amount: defaultAmount, method: kind === "pay" ? "cash" : "bank", account: "", reference: "", date: today() });
  const from = usePayFromAccounts(open ? bill.company_id : undefined, f.values.method as PayMethod);
  const methods = kind === "pay" ? PAY_METHODS : PAY_METHODS.filter((m) => m !== "card");

  const save = useMutation({
    meta: { silent: true },
    mutationFn: (): Promise<unknown> => {
      const common = { amount: f.values.amount, method: f.values.method as PayMethod, payment_account_id: f.values.account || null, external_ref: f.values.reference.trim() || null };
      const params = { params: { path: { bill_id: bill.id } } };
      return kind === "pay"
        ? unwrap(api.POST("/api/v1/purchasing/bills/{bill_id}/pay", { ...params, body: { ...common, paid_on: f.values.date } }))
        : unwrap(api.POST("/api/v1/purchasing/bills/{bill_id}/refund", { ...params, body: { ...common, method: common.method as "cash", received_on: f.values.date } }));
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["purchasing"] });
      toast(t(kind === "pay" ? "paidToast" : "refundToast", { number: bill.number }), "ok");
      onClose();
    },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };

  return (
    <Drawer open={open} onClose={onClose} title={t(kind === "pay" ? "payBill" : "recordRefund", { number: bill.number })}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="settle-form" loading={save.isPending} disabled={!(Number(f.values.amount) > 0) || (from.required && from.ready && !f.values.account)}>{t(kind === "pay" ? "pay" : "recordRefundShort")}</Button></>}>
      <form id="settle-form" onSubmit={submit} className="space-y-4">
        <FormGrid>
          <Field label={t("amount")} required error={f.error("amount")}><NumberInput value={f.values.amount} onChange={(v) => f.set("amount", v)} autoFocus /></Field>
          <Field label={t(kind === "pay" ? "paidOn" : "receivedOn")} error={f.error("paid_on") ?? f.error("received_on")}><Input type="date" max={today()} {...f.bind("date")} /></Field>
          <Field label={t("method")} error={f.error("method")}>
            <Select {...f.bind("method")}>{methods.map((m) => <option key={m} value={m}>{t(`methods.${m}`)}</option>)}</Select>
          </Field>
          <PayFrom companyId={bill.company_id} method={f.values.method as PayMethod} value={f.values.account} onChange={(id) => f.set("account", id)} error={f.error("payment_account_id")} />
        </FormGrid>
        <Field label={t("reference")} hint={t("referenceHint")} error={f.error("external_ref")}><Input {...f.bind("reference")} maxLength={60} /></Field>
      </form>
    </Drawer>
  );
}
