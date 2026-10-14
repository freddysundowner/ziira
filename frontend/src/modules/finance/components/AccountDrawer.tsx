import { useState } from "react";

import {
  api, Alert, Button, Combobox, Drawer, ErrorState, Field, FormGrid, Input, orNull, Select, Skeleton, Switch, toast, unwrap, useFormState, useMutation, useQuery, useQueryClient,
  useTranslation,
} from "@/sdk";

import { type Account, accountOptions, useAccounts } from "../api";

const TYPES = ["asset", "liability", "equity", "income", "expense"] as const;
type AccountType = (typeof TYPES)[number];

interface Props {
  open: boolean;
  onClose: () => void;
  companyId: string;
  /** Omit to add a new account. */
  account?: Account;
}

/** Add an account, or edit one: its name, whether it is in use, and what the accountant's software calls it. */
export function AccountDrawer({ open, onClose, companyId, account }: Props) {
  const mappings = useQuery({
    enabled: open && !!account && !!companyId, queryKey: ["finance", "mappings", companyId],
    queryFn: () => unwrap(api.GET("/api/v1/finance/account-mappings", { params: { query: { company_id: companyId } } })),
  });
  if (!open) return null;
  if (account && !mappings.isSuccess) {
    return (
      <Drawer open onClose={onClose} title={account.name}>
        {mappings.error ? <ErrorState message={mappings.error.message} onRetry={() => void mappings.refetch()} /> : <Skeleton className="h-40 w-full" />}
      </Drawer>
    );
  }
  const mapped = account ? mappings.data?.find((m) => m.account_id === account.id) : undefined;
  return <AccountForm onClose={onClose} companyId={companyId} account={account} hadMapping={!!mapped} initialCode={mapped?.external_code ?? ""} initialName={mapped?.external_name ?? ""} />;
}

function AccountForm({ onClose, companyId, account, hadMapping, initialCode, initialName }: {
  onClose: () => void; companyId: string; account?: Account; hadMapping: boolean; initialCode: string; initialName: string;
}) {
  const { t } = useTranslation("finance");
  const qc = useQueryClient();
  const accounts = useAccounts(companyId);
  const f = useFormState({ code: "", name: account?.name ?? "", type: "asset", subtype: "", parent_id: "", external_code: initialCode, external_name: initialName });
  const [active, setActive] = useState(account?.is_active ?? true);

  const done = (message: string) => {
    void qc.invalidateQueries({ queryKey: ["finance"] });
    toast(message, "ok");
    onClose();
  };

  const create = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/finance/accounts", { body: {
      company_id: companyId, code: f.values.code.trim(), name: f.values.name.trim(), type: f.values.type as AccountType, subtype: orNull(f.values.subtype), parent_id: f.values.parent_id || null } })),
    onSuccess: (a) => done(t("accounts.created", { name: a.name })),
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });

  const save = useMutation({
    meta: { silent: true },
    mutationFn: async () => {
      if (!account) return;
      await unwrap(api.PATCH("/api/v1/finance/accounts/{account_id}", { params: { path: { account_id: account.id } }, body: { name: f.values.name.trim(), is_active: account.is_control ? undefined : active } }));
      const code = orNull(f.values.external_code);
      const name = orNull(f.values.external_name);
      const path = { params: { path: { account_id: account.id }, query: { company_id: companyId } } };
      if (code || name) await unwrap(api.PUT("/api/v1/finance/account-mappings/{account_id}", { ...path, body: { external_code: code, external_name: name } }));
      else if (hadMapping) await unwrap(api.DELETE("/api/v1/finance/account-mappings/{account_id}", path));
    },
    onSuccess: () => done(t("accounts.saved")),
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });

  const sameType = accountOptions(accounts.data, { types: [f.values.type] });
  return (
    <Drawer open onClose={onClose} title={account ? `${account.code} · ${account.name}` : t("accounts.new")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="account-form" loading={create.isPending || save.isPending}>{t("save")}</Button></>}>
      <form id="account-form" className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (account) save.mutate();
        else create.mutate(); }}>
        {!account ? (
          <>
            <FormGrid>
              <Field label={t("code")} required error={f.error("code")}><Input {...f.bind("code")} required maxLength={20} autoFocus /></Field>
              <Field label={t("type")} required><Select {...f.bind("type")}>{TYPES.map((x) => <option key={x} value={x}>{t(`accountTypes.${x}`)}</option>)}</Select></Field>
            </FormGrid>
            <Field label={t("name")} required error={f.error("name")}><Input {...f.bind("name")} required maxLength={200} /></Field>
            <Field label={t("accounts.subtype")} error={f.error("subtype")} hint={t("accounts.subtypeHint")}><Input {...f.bind("subtype")} maxLength={40} /></Field>
            <Field label={t("accounts.parent")} hint={t("accounts.parentHint")}>
              <Combobox clearable value={f.values.parent_id} onChange={(v) => f.set("parent_id", v)} options={sameType} placeholder={t("accounts.noParent")} />
            </Field>
          </>
        ) : (
          <>
            {account.is_control && <Alert tone="info">{t("accounts.controlHint")}</Alert>}
            <Field label={t("name")} required error={f.error("name")}><Input {...f.bind("name")} required maxLength={200} /></Field>
            <div className="flex items-center justify-between gap-3 rounded-lg border border-line px-3 py-2.5">
              <div><p className="text-sm font-medium">{t("accounts.inUse")}</p><p className="text-xs text-muted">{t("accounts.inUseHint")}</p></div>
              <Switch label={t("accounts.inUse")} checked={active} onChange={setActive} disabled={account.is_control} />
            </div>
            <div className="space-y-3 rounded-xl bg-sunken p-4">
              <div><h3 className="text-sm font-semibold">{t("accounts.mapping")}</h3><p className="text-xs text-muted">{t("accounts.mappingHint")}</p></div>
              <FormGrid>
                <Field label={t("accounts.externalCode")} error={f.error("external_code")}><Input {...f.bind("external_code")} maxLength={40} /></Field>
                <Field label={t("accounts.externalName")} error={f.error("external_name")}><Input {...f.bind("external_name")} maxLength={100} /></Field>
              </FormGrid>
            </div>
          </>
        )}
      </form>
    </Drawer>
  );
}
