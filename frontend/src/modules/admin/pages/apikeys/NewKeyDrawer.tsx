import { type FormEvent, useMemo, useState } from "react";

import {
  api, Button, Checkbox, Drawer, ErrorState, Field, Input, Select, SkeletonRows, humanise, toast, unwrap, useCompanies, useFormState, useMutation, useQuery, useQueryClient, useTranslation,
} from "@/sdk";

import { groupByUnit, toggleScopes } from "./scopes";

export default function NewKeyDrawer({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (name: string, key: string) => void }) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const perms = useQuery({ enabled: open, queryKey: ["permissions"], queryFn: () => unwrap(api.GET("/api/v1/permissions")) });
  const groups = useMemo(() => groupByUnit(perms.data ?? []), [perms.data]);
  const f = useFormState({ name: "", expires: "", rate: "", company: "" });
  const companies = useCompanies();
  const [readOnly, setReadOnly] = useState(false);
  const [scopes, setScopes] = useState<string[]>([]);
  const create = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/api-keys", {
      body: {
        name: f.values.name.trim(), scopes, read_only: readOnly, company_id: f.values.company || null,
        rate_limit_per_minute: f.values.rate ? Number(f.values.rate) : null, expires_at: f.values.expires ? `${f.values.expires}T23:59:59Z` : null,
      },
    })),
    onSuccess: (data) => { void qc.invalidateQueries({ queryKey: ["api-keys"] }); onCreated(f.values.name.trim(), data.key); f.reset(); setScopes([]); setReadOnly(false); },
    onError: (e) => { f.fail(e); toast(e.message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); create.mutate(); };

  return (
    <Drawer open={open} onClose={onClose} title={t("newKey")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="new-key" loading={create.isPending} disabled={scopes.length === 0}>{t("createKey")}</Button></>}>
      <form id="new-key" onSubmit={submit} className="space-y-5">
        <Field label={t("keyName")} hint={t("keyNameHint")} required error={f.error("name")}><Input {...f.bind("name")} required maxLength={100} autoFocus /></Field>
        <Field label={t("expires")} hint={t("expiresHint")} error={f.error("expires_at")}><Input type="date" {...f.bind("expires")} /></Field>
        <Checkbox checked={readOnly} onChange={(e) => setReadOnly(e.target.checked)} label={<span>{t("keys.readOnly")} <span className="text-muted">{t("keys.readOnlyHint")}</span></span>} />
        {(companies.data?.length ?? 0) > 1 && (
          <Field label={t("keys.company")} hint={t("keys.companyHint")} error={f.error("company_id")}>
            <Select {...f.bind("company")}><option value="">{t("keys.allCompanies")}</option>{companies.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>
          </Field>
        )}
        <Field label={t("keys.rateLimit")} hint={t("keys.rateLimitHint")} error={f.error("rate_limit_per_minute")}>
          <Input type="number" min={1} max={100000} inputMode="numeric" {...f.bind("rate")} />
        </Field>
        <div>
          <p className="mb-1 text-sm font-medium">{t("scopes")}</p>
          <p className="mb-3 text-xs text-muted">{t("scopesHint")}</p>
          {perms.error ? <ErrorState message={perms.error.message} onRetry={() => void perms.refetch()} /> : !perms.data ? <SkeletonRows rows={4} cols={2} /> : (
            <div className="space-y-3">
              {groups.map((g) => {
                const codes = g.permissions.map((p) => p.code);
                const all = codes.every((c) => scopes.includes(c));
                return (
                  <fieldset key={g.unit} className="rounded-xl border border-line p-3">
                    <legend className="px-1"><Checkbox label={<span className="font-semibold">{humanise(g.unit)}</span>} checked={all} onChange={(e) => setScopes(toggleScopes(scopes, codes, e.target.checked))} /></legend>
                    <div className="grid gap-2 sm:grid-cols-2">
                      {g.permissions.map((p) => (
                        <Checkbox key={p.code} checked={scopes.includes(p.code)} onChange={(e) => setScopes(toggleScopes(scopes, [p.code], e.target.checked))}
                          label={<span title={p.description}><code className="text-xs">{p.code}</code></span>} />
                      ))}
                    </div>
                  </fieldset>
                );
              })}
            </div>
          )}
          {f.error("scopes") && <p role="alert" className="mt-1 text-xs text-bad">{f.error("scopes")}</p>}
        </div>
      </form>
    </Drawer>
  );
}
