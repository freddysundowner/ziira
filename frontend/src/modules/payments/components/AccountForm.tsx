import { useEffect, useState } from "react";

import {
  api, Button, Drawer, Field, FormGrid, Input, orNull, Select, Switch, toast, unwrap, useCompany, useFormState, useMutation, useQueryClient,
  useTranslation,
} from "@/sdk";

import type { PaymentAccount } from "../types";
import { ProviderFields } from "./ProviderFields";
import { fieldValues, offeredProviders, usePaymentProviders } from "./usePaymentProviders";

type Account = PaymentAccount;
const KINDS = ["cash", "mobile_money", "bank", "card"] as const;

/** Create (no `account`) or edit a payment account. The providers on offer, and each one's own settings form, come from the server. */
export function AccountForm({ open, onClose, account }: { open: boolean; onClose: () => void; account?: Account }) {
  const { t } = useTranslation("payments");
  const qc = useQueryClient();
  const { company, companies } = useCompany();
  const editing = !!account;
  const f = useFormState({ kind: "mobile_money", name: "", shortcode: "", bank_account_masked: "", provider: "", environment: "sandbox", branch_id: "", company_id: "" });
  const providers = usePaymentProviders(open && !account);
  const offered = offeredProviders(providers.data?.providers ?? []);
  const [settings, setSettings] = useState<Record<string, string>>({});
  const [active, setActive] = useState(true);
  const [name, setName] = useState("");
  const { reset } = f;
  useEffect(() => {
    if (!open) return;
    reset(); setSettings({}); setActive(account?.is_active ?? true); setName(account?.name ?? "");
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const companyId = f.values.company_id || company?.id || "";
  const branches = companies.find((c) => c.id === companyId)?.branches ?? [];
  const kind = f.values.kind;
  const chosen = offered.find((p) => p.name === f.values.provider);

  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => {
      if (account) {
        return unwrap(api.PATCH("/api/v1/payments/accounts/{account_id}", { params: { path: { account_id: account.id } }, body: { name: name.trim(), is_active: active } }));
      }
      const v = f.values;
      return unwrap(api.POST("/api/v1/payments/accounts", { body: {
        company_id: companyId, branch_id: orNull(v.branch_id), kind: kind as "cash", name: v.name.trim(), shortcode: orNull(v.shortcode),
        bank_account_masked: orNull(v.bank_account_masked), environment: v.environment as "sandbox", provider: orNull(v.provider),
        provider_config: kind === "mobile_money" && chosen ? fieldValues(chosen.config_fields, settings) : null } }));
    },
    onSuccess: (a) => { void qc.invalidateQueries({ queryKey: ["payment-accounts"] }); toast(t(editing ? "accountUpdated" : "accountCreated", { name: a.name }), "ok"); onClose(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });

  return (
    <Drawer open={open} onClose={onClose} title={editing ? t("editAccount") : t("newAccount")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="account-form" loading={save.isPending}>{t("save")}</Button></>}>
      <form id="account-form" className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        {editing ? (
          <>
            <Field label={t("name")} required error={f.error("name")}><Input value={name} onChange={(e) => setName(e.target.value)} required autoFocus /></Field>
            <div className="flex items-center justify-between rounded-lg border border-line p-3">
              <div><p className="text-sm font-medium">{t("accountActive")}</p><p className="text-xs text-muted">{t("accountActiveHint")}</p></div>
              <Switch checked={active} onChange={setActive} label={t("accountActive")} />
            </div>
          </>
        ) : (
          <>
            <FormGrid>
              <Field label={t("kind")}><Select {...f.bind("kind")}>{KINDS.map((k) => <option key={k} value={k}>{t(`methods.${k}`)}</option>)}</Select></Field>
              <Field label={t("name")} required error={f.error("name")}><Input {...f.bind("name")} required autoFocus placeholder={t("namePlaceholder")} /></Field>
            </FormGrid>
            {kind === "mobile_money" && (
              <>
                <FormGrid>
                  <Field label={t("shortcode")} hint={t("shortcodeHint")} error={f.error("shortcode")}><Input {...f.bind("shortcode")} maxLength={20} /></Field>
                  <Field label={t("environment")} error={f.error("environment")}>
                    <Select {...f.bind("environment")}><option value="sandbox">{t("environments.sandbox")}</option><option value="production">{t("environments.production")}</option></Select>
                  </Field>
                </FormGrid>
                <Field label={t("provider")} hint={t("providerHint")} error={f.error("provider")}>
                  <Select {...f.bind("provider")}>
                    <option value="">{t("providerManual")}</option>
                    {offered.map((p) => <option key={p.name} value={p.name}>{p.title}{p.development_only ? ` (${t("developmentOnly")})` : ""}</option>)}
                  </Select>
                </Field>
                {chosen && chosen.config_fields.length > 0 && (
                  <FormGrid><ProviderFields fields={chosen.config_fields} values={settings} onChange={(k, v) => setSettings((x) => ({ ...x, [k]: v }))} /></FormGrid>
                )}
              </>
            )}
            {(kind === "bank" || kind === "card") && (
              <Field label={t("accountNumberMasked")} hint={t("accountNumberHint")} error={f.error("bank_account_masked")}><Input {...f.bind("bank_account_masked")} maxLength={40} placeholder="****1234" /></Field>
            )}
            <FormGrid>
              {companies.length > 1 && (
                <Field label={t("company")}>
                  <Select value={companyId} onChange={(e) => { f.set("company_id", e.target.value); f.set("branch_id", ""); }}>{companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>
                </Field>
              )}
              {branches.length > 1 && (
                <Field label={t("branch")} hint={t("branchHint")} error={f.error("branch_id")}>
                  <Select {...f.bind("branch_id")}><option value="">{t("allBranches")}</option>{branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</Select>
                </Field>
              )}
            </FormGrid>
          </>
        )}
      </form>
    </Drawer>
  );
}
