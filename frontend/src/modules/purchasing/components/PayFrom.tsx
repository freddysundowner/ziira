import { type FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  Alert, api, Button, Drawer, Field, Input, Select, toast, unwrap, useCan, useMutation, useQueryClient, useTranslation,
} from "@/sdk";

import { usePaymentAccounts } from "../hooks";
import { ACCOUNT_KINDS_FOR_METHOD } from "../lib";
import type { PayMethod } from "../types";

/** The accounts a method can pay from. `required`: the server refuses this method without one (cash falls back to the branch's till cash). */
export function usePayFromAccounts(companyId: string | undefined, method: PayMethod) {
  const all = usePaymentAccounts(companyId);
  const accounts = (all.data ?? []).filter((a) => a.is_active && ACCOUNT_KINDS_FOR_METHOD[method].includes(a.kind));
  return { accounts, required: method !== "cash", ready: all.isSuccess, unavailable: all.isError };
}

/**
 * "Pay from": the money account a supplier payment goes through. When there is none for the method it says so and lets a person
 * who may manage payment accounts add one right here, instead of leaving the payment stuck.
 */
export function PayFrom({ companyId, method, value, onChange, error }: {
  companyId: string | undefined; method: PayMethod; value: string; onChange: (id: string) => void; error?: string | null;
}) {
  const { t } = useTranslation("purchasing");
  const { accounts, required, ready, unavailable } = usePayFromAccounts(companyId, method);
  const canManage = useCan("payments.manage");
  const [adding, setAdding] = useState(false);
  const only = accounts.length === 1 ? accounts[0]!.id : "";
  const known = accounts.some((a) => a.id === value);

  // One fitting account is the obvious choice; an account chosen for another method no longer fits.
  useEffect(() => {
    if (value && !known && ready) onChange(required ? only : "");
    else if (!value && required && only) onChange(only);
  }, [value, known, ready, required, only, onChange]);

  if (unavailable || !companyId) return null;
  if (accounts.length === 0) {
    if (!ready || !required) return null;
    const canAdd = canManage && method !== "mobile_money";
    return (
      <div className="sm:col-span-2 lg:col-span-3">
        <Alert tone="warn">
          <p className="font-medium">{t("noAccountFor", { method: t(`methods.${method}`) })}</p>
          <p className="mt-1">{canAdd ? t("noAccountCanAdd") : canManage ? t("noAccountSetUpIn") : t("noAccountAskOwner")}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {canAdd && <Button size="sm" onClick={() => setAdding(true)}>{t("addPayAccount", { method: t(`methods.${method}`) })}</Button>}
            {canManage && method === "mobile_money" && <Link className="text-sm font-medium underline" to="/payments/accounts">{t("openPaymentAccounts")}</Link>}
          </div>
        </Alert>
        {adding && <PayAccountDrawer companyId={companyId} method={method} onClose={() => setAdding(false)} onCreated={onChange} />}
      </div>
    );
  }
  return (
    <Field label={t("fromAccount")} required={required} error={error}>
      <Select value={value} onChange={(e) => onChange(e.target.value)}>
        {required ? (!only && <option value="">{t("chooseAccount")}</option>) : <option value="">{t("branchTillCash")}</option>}
        {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
      </Select>
    </Field>
  );
}

/** A bank or card account added from the payment dialog. Mobile money accounts need provider set-up, so they are added in Payments. */
function PayAccountDrawer({ companyId, method, onClose, onCreated }: { companyId: string; method: PayMethod; onClose: () => void; onCreated: (id: string) => void }) {
  const { t } = useTranslation("purchasing");
  const qc = useQueryClient();
  const kind = method === "card" ? "card" : "bank";
  const [name, setName] = useState("");
  const [masked, setMasked] = useState("");
  const create = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/payments/accounts", { body: { company_id: companyId, kind, provider: "daraja", environment: "sandbox", name: name.trim(), bank_account_masked: kind === "bank" && masked.trim() ? masked.trim() : null } })),
    onSuccess: async (a) => {
      await qc.invalidateQueries({ queryKey: ["purchasing", "pay-accounts"] });
      toast(t("payAccountAdded", { name: a.name }), "ok");
      onCreated(a.id);
      onClose();
    },
  });
  // The drawer sits inside the payment page's own form in the React tree: its submit must not also submit that one.
  const submit = (e: FormEvent) => { e.preventDefault(); e.stopPropagation(); create.mutate(); };
  return (
    <Drawer open onClose={onClose} title={t("addPayAccount", { method: t(`methods.${method}`) })}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="pay-account-form" loading={create.isPending} disabled={!name.trim()}>{t("save")}</Button></>}>
      <form id="pay-account-form" onSubmit={submit} className="space-y-4">
        <Field label={t("payAcctName")} required hint={t("payAcctNameHint")}><Input value={name} onChange={(e) => setName(e.target.value)} autoFocus maxLength={200} /></Field>
        {kind === "bank" && <Field label={t("payAcctNumber")} hint={t("payAcctNumberHint")}><Input value={masked} onChange={(e) => setMasked(e.target.value)} maxLength={40} placeholder="****4821" /></Field>}
      </form>
    </Drawer>
  );
}
