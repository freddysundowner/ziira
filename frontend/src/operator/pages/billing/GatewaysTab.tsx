import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Alert, Badge, Button, Card, ErrorState, Field, Input, Skeleton, toast, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { CopyButton } from "../../components/bits";
import { type Gateway, gatewayBody, gatewayDirty, gatewayDraft, type GatewayDraft } from "../../helpers/gateway";
import { useOperatorCan } from "../../me";
import { useChange } from "../../stepUp";

const KEY = ["operator", "payment-gateways"];

/** Payment methods: one card per installed payment plugin, with its switch, settings, write-only secrets, a connection test and the address to register with the provider. */
export default function GatewaysTab() {
  const { t } = useTranslation("operator");
  const list = useQuery({ queryKey: KEY, queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/payment-gateways")) });
  if (list.isPending) return <Skeleton className="h-48 w-full" />;
  if (list.isError) return <ErrorState title={t("billing.gateways.loadFailed")} message={list.error.message} onRetry={() => void list.refetch()} />;
  if (list.data.length === 0) return <Alert tone="info">{t("billing.gateways.none")}</Alert>;
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">{t("billing.gateways.intro")}</p>
      {list.data.map((g) => <GatewayCard key={`${g.name}:${g.updated_at}`} gateway={g} onSaved={() => void list.refetch()} />)}
    </div>
  );
}

function GatewayCard({ gateway: g, onSaved }: { gateway: Gateway; onSaved: () => void }) {
  const { t } = useTranslation("operator");
  const editable = useOperatorCan("platform.billing");
  const [draft, setDraft] = useState<GatewayDraft>(gatewayDraft(g));
  const [problem, setProblem] = useState<string | null>(null);
  const [test, setTest] = useState<{ ok: boolean; message: string } | null>(null);
  const dirty = gatewayDirty(g, draft);
  const save = useChange(() => opUnwrap(opApi.PUT("/api/v1/operator/payment-gateways/{name}", { params: { path: { name: g.name } }, body: gatewayBody(g, draft) })), {
    onSuccess: () => { toast(t("billing.gateways.saved", { name: g.title }), "ok"); onSaved(); },
    onError: (e) => setProblem(e.message),
  });
  const run = useChange(() => opUnwrap(opApi.POST("/api/v1/operator/payment-gateways/{name}/test", { params: { path: { name: g.name } } })), {
    onSuccess: (r) => setTest(r), onError: (e) => setTest({ ok: false, message: e.message }),
  });
  const set = (next: GatewayDraft) => { setDraft(next); setProblem(null); };
  return (
    <Card title={g.title} description={g.description}
      actions={<Badge tone={g.enabled ? "ok" : "neutral"}>{g.enabled ? t("billing.gateways.on") : t("billing.gateways.off")}</Badge>}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (dirty && editable && !save.isPending) { setProblem(null); save.mutate(undefined); } }}>
        <p className="text-xs text-muted">
          {t("billing.gateways.serves", { currencies: g.currencies.join(", ") || t("billing.gateways.any"), countries: g.countries.join(", ") || t("billing.gateways.worldwide") })}
        </p>
        <fieldset disabled={!editable} className="space-y-3">
          <label className="flex items-center gap-2 text-sm font-medium">
            <input type="checkbox" checked={draft.enabled} onChange={(e) => set({ ...draft, enabled: e.target.checked })} />
            {t("billing.gateways.enable")}
          </label>
          {g.fields.map((f) => f.secret ? (
            <Field key={f.name} label={f.label} hint={f.help} required={f.required}>
              <div className="flex gap-2">
                <Input type="password" autoComplete="off" value={draft.secrets[f.name] ?? ""} disabled={draft.cleared.includes(f.name)}
                  placeholder={f.is_set ? t("billing.gateways.secretSet") : t("billing.gateways.secretNotSet")}
                  onChange={(e) => set({ ...draft, secrets: { ...draft.secrets, [f.name]: e.target.value } })} />
                {f.is_set && (
                  <Button type="button" size="sm" variant="ghost"
                    onClick={() => set({ ...draft, cleared: draft.cleared.includes(f.name) ? draft.cleared.filter((n) => n !== f.name) : [...draft.cleared, f.name] })}>
                    {draft.cleared.includes(f.name) ? t("billing.gateways.keep") : t("billing.gateways.remove")}
                  </Button>
                )}
              </div>
            </Field>
          ) : (
            <Field key={f.name} label={f.label} hint={f.help} required={f.required}>
              <Input value={draft.values[f.name] ?? ""} maxLength={500} onChange={(e) => set({ ...draft, values: { ...draft.values, [f.name]: e.target.value } })} />
            </Field>
          ))}
          <Field label={t("billing.gateways.defaultFor")} hint={t("billing.gateways.defaultForHint")}>
            <Input value={draft.defaultFor} maxLength={120} className="font-mono" onChange={(e) => set({ ...draft, defaultFor: e.target.value })} />
          </Field>
        </fieldset>
        <div>
          <p className="text-sm font-medium">{t("billing.gateways.webhook")}</p>
          {g.webhook_url ? (
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <code className="break-all rounded bg-sunken px-2 py-1 text-xs">{g.webhook_url}</code>
              <CopyButton text={g.webhook_url} label={t("billing.gateways.copy")} />
            </div>
          ) : <Alert tone="warn" className="mt-1">{g.webhook_problem}</Alert>}
          <p className="mt-1 text-xs text-muted">{t("billing.gateways.webhookHint")}</p>
        </div>
        {problem && <Alert tone="bad">{problem}</Alert>}
        {test && <Alert tone={test.ok ? "ok" : "bad"}>{test.message}</Alert>}
        {editable && (
          <div className="flex flex-wrap justify-end gap-2">
            <Button type="button" variant="secondary" size="sm" loading={run.isPending} disabled={!g.configured || dirty} onClick={() => { setTest(null); run.mutate(undefined); }}>{t("billing.gateways.test")}</Button>
            <Button type="submit" size="sm" loading={save.isPending} disabled={!dirty}>{t("billing.settings.save")}</Button>
          </div>
        )}
      </form>
    </Card>
  );
}
