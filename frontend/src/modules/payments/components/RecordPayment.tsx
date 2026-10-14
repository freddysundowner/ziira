import { useEffect } from "react";

import {
  api, Button, Drawer, Field, FormGrid, Input, NumberInput, orNull, Select, today, toast, unwrap, useCompany, useFormState, useMutation, useQueryClient,
  useTranslation,
} from "@/sdk";

import { usePaymentAccounts } from "./usePaymentAccounts";

export const METHODS = ["cash", "mobile_money", "bank", "card", "cheque", "other"] as const;
const PARTIES = ["customer", "supplier", "employee", "other"] as const;

/** Record money received or paid out that is not already captured by a sale or a customer receipt. */
export function RecordPayment({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation("payments");
  const qc = useQueryClient();
  const { company, companies } = useCompany();
  const f = useFormState({ direction: "in", method: "cash", amount: "", payment_account_id: "", business_date: today(), external_ref: "", phone: "", party_type: "", branch_id: "", company_id: "" });
  const { reset } = f;
  useEffect(() => { if (open) reset(); }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const companyId = f.values.company_id || company?.id || "";
  const branches = companies.find((c) => c.id === companyId)?.branches ?? [];
  const accounts = usePaymentAccounts({ enabled: open });
  const usable = (accounts.data ?? []).filter((a) => a.company_id === companyId && a.kind === f.values.method);
  const mobile = f.values.method === "mobile_money";

  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => {
      const v = f.values;
      return unwrap(api.POST("/api/v1/payments/payments", { body: {
        company_id: companyId, branch_id: orNull(v.branch_id), method: v.method as "cash", direction: v.direction as "in", amount: v.amount,
        payment_account_id: orNull(v.payment_account_id), business_date: orNull(v.business_date), external_ref: orNull(v.external_ref), phone: mobile ? orNull(v.phone) : null,
        party_type: (v.party_type || null) as "customer" | null } }));
    },
    onSuccess: (p) => { void qc.invalidateQueries({ queryKey: ["payments"] }); toast(t("recorded", { number: p.number }), "ok"); onClose(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });

  return (
    <Drawer open={open} onClose={onClose} title={t("recordPayment")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="payment-form" loading={save.isPending}>{t("save")}</Button></>}>
      <form id="payment-form" className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <p className="text-sm text-muted">{t("recordHint")}</p>
        <FormGrid>
          <Field label={t("direction")}>
            <Select {...f.bind("direction")}><option value="in">{t("directions.in")}</option><option value="out">{t("directions.out")}</option></Select>
          </Field>
          <Field label={t("method")}>
            <Select value={f.values.method} onChange={(e) => { f.set("method", e.target.value); f.set("payment_account_id", ""); }}>
              {METHODS.map((m) => <option key={m} value={m}>{t(`methods.${m}`)}</option>)}
            </Select>
          </Field>
        </FormGrid>
        <FormGrid>
          <Field label={t("amount")} required error={f.error("amount")}><NumberInput value={f.values.amount} onChange={(v) => f.set("amount", v)} required autoFocus /></Field>
          <Field label={t("date")} error={f.error("business_date")}><Input type="date" {...f.bind("business_date")} max={today()} /></Field>
        </FormGrid>
        <Field label={t("account")} hint={usable.length === 0 ? t("noAccountForMethod") : undefined} error={f.error("payment_account_id")}>
          <Select {...f.bind("payment_account_id")}><option value="">{t("accountAuto")}</option>{usable.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select>
        </Field>
        <Field label={t("reference")} hint={t("referenceHint")} error={f.error("external_ref")}><Input {...f.bind("external_ref")} maxLength={60} /></Field>
        {mobile && <Field label={t("phone")} hint={t("phoneHint")} error={f.error("phone")}><Input type="tel" {...f.bind("phone")} /></Field>}
        <FormGrid>
          <Field label={t("party")} error={f.error("party_type")}>
            <Select {...f.bind("party_type")}><option value="">{t("noParty")}</option>{PARTIES.map((p) => <option key={p} value={p}>{t(`parties.${p}`)}</option>)}</Select>
          </Field>
          {branches.length > 1 && (
            <Field label={t("branch")} error={f.error("branch_id")}>
              <Select {...f.bind("branch_id")}><option value="">{t("noBranch")}</option>{branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</Select>
            </Field>
          )}
        </FormGrid>
        {companies.length > 1 && (
          <Field label={t("company")}>
            <Select value={companyId} onChange={(e) => { f.set("company_id", e.target.value); f.set("payment_account_id", ""); f.set("branch_id", ""); }}>{companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>
          </Field>
        )}
      </form>
    </Drawer>
  );
}
