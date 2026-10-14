import { useEffect, useState } from "react";

import {
  api, Button, Checkbox, Drawer, Field, FormGrid, Input, NumberInput, orNull, Select, today, toast, unwrap, useCompany, useFormState, useMutation, useQuery,
  useQueryClient, useTranslation, type Schemas,
} from "@/sdk";

const METHODS = ["cash", "mobile_money", "bank", "card", "cheque", "other"] as const;

/** Record money a customer paid. By default it settles their oldest invoices first (the server decides how). */
export function ReceivePayment({ open, onClose, customer }: { open: boolean; onClose: () => void; customer: Schemas["CustomerOut"] }) {
  const { t } = useTranslation("crm");
  const qc = useQueryClient();
  const { companies } = useCompany(customer.company_id);
  const branches = companies.find((c) => c.id === customer.company_id)?.branches ?? [];
  const f = useFormState({ amount: "", method: "cash", external_ref: "", received_on: today(), branch_id: "", payment_account_id: "" });
  const [hold, setHold] = useState(false);
  const { reset } = f;
  useEffect(() => { if (open) { reset(); setHold(false); } }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const needsAccount = f.values.method !== "cash";
  const accounts = useQuery({
    enabled: open && needsAccount, queryKey: ["payment-accounts", customer.company_id, f.values.method],
    queryFn: () => unwrap(api.GET("/api/v1/payments/accounts", { params: { query: { company_id: customer.company_id, kind: f.values.method } } })),
    retry: false,
  });

  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/pos/receipts", { body: {
      customer_id: customer.id, amount: f.values.amount, method: f.values.method as "cash", branch_id: orNull(f.values.branch_id),
      payment_account_id: orNull(f.values.payment_account_id), external_ref: orNull(f.values.external_ref), received_on: f.values.received_on || null, hold_balance: hold } })),
    onSuccess: (r) => {
      for (const key of ["customer-balance", "customer-statement", "customer-receipts", "customer-invoices", "ageing"]) void qc.invalidateQueries({ queryKey: [key] });
      toast(t("receiptRecorded", { number: r.number }), "ok");
      onClose();
    },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });

  return (
    <Drawer open={open} onClose={onClose} title={t("receivePayment")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="receipt-form" loading={save.isPending}>{t("recordPayment")}</Button></>}>
      <form id="receipt-form" className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <p className="text-sm text-muted">{t("receiveFrom", { name: customer.name })}</p>
        <FormGrid>
          <Field label={t("amount")} required error={f.error("amount")}><NumberInput value={f.values.amount} onChange={(v) => f.set("amount", v)} required autoFocus /></Field>
          <Field label={t("receivedOn")} error={f.error("received_on")}><Input type="date" {...f.bind("received_on")} max={today()} /></Field>
        </FormGrid>
        <Field label={t("method")} error={f.error("method")}>
          <Select value={f.values.method} onChange={(e) => { f.set("method", e.target.value); f.set("payment_account_id", ""); }}>
            {METHODS.map((m) => <option key={m} value={m}>{t(`methods.${m}`)}</option>)}
          </Select>
        </Field>
        {needsAccount && accounts.data && accounts.data.length > 0 && (
          <Field label={t("paidInto")} error={f.error("payment_account_id")}>
            <Select {...f.bind("payment_account_id")}><option value="">{t("chooseAccount")}</option>{accounts.data.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select>
          </Field>
        )}
        <Field label={t("reference")} hint={t("referenceHint")} error={f.error("external_ref")}><Input {...f.bind("external_ref")} maxLength={60} /></Field>
        {branches.length > 1 && (
          <Field label={t("branch")} error={f.error("branch_id")}>
            <Select {...f.bind("branch_id")}><option value="">{t("anyBranch")}</option>{branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</Select>
          </Field>
        )}
        <Checkbox label={t("holdBalance")} checked={hold} onChange={(e) => setHold(e.target.checked)} />
        <p className="text-xs text-muted">{t("settlesOldest")}</p>
      </form>
    </Drawer>
  );
}
