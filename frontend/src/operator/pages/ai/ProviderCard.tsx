import { useState } from "react";

import { Alert, Badge, Button, Card, Field, formatDate, Input, Select, toast, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { type AiOverview, type AiProvider, FEATURES, maskedKey, providerBody, providerDirty, providerDraft, type ProviderDraft, TIER_TONE, usd } from "../../helpers/ai";
import { useOperatorCan } from "../../me";
import { useChange } from "../../stepUp";
import { DefaultDialog } from "./DefaultDialog";
import { QualityDialog } from "./QualityDialog";

/** One provider: switch, write-only key, a model for each feature with its price, the live list, a connection test and the data-terms acknowledgement. */
export function ProviderCard({ provider: p, overview, onChanged }: { provider: AiProvider; overview: AiOverview; onChanged: () => void }) {
  const { t } = useTranslation("operator");
  const editable = useOperatorCan("platform.ai");
  const [draft, setDraft] = useState<ProviderDraft>(providerDraft(p));
  const [problem, setProblem] = useState<string | null>(null);
  const [test, setTest] = useState<{ ok: boolean; message: string } | null>(null);
  const [dialog, setDialog] = useState<"default" | "quality" | null>(null);
  const dirty = providerDirty(p, draft);
  const set = (next: ProviderDraft) => { setDraft(next); setProblem(null); };
  const save = useChange(() => opUnwrap(opApi.PUT("/api/v1/operator/ai/providers/{name}", { params: { path: { name: p.name } }, body: providerBody(p, draft) })), {
    onSuccess: () => { toast(t("ai.saved", { name: p.title }), "ok"); onChanged(); },
    onError: (e) => setProblem(e.message),
  });
  const refresh = useChange(() => opUnwrap(opApi.POST("/api/v1/operator/ai/providers/{name}/refresh-models", { params: { path: { name: p.name } } })), {
    onSuccess: (r) => { toast(t("ai.refreshed", { count: r.count }), r.missing_chosen.length ? "warn" : "ok"); onChanged(); },
    onError: (e) => setProblem(e.message),
  });
  const probe = useChange(() => opUnwrap(opApi.POST("/api/v1/operator/ai/providers/{name}/test", { params: { path: { name: p.name } } })), {
    onSuccess: (r) => { setTest({ ok: r.ok, message: r.ok ? t("ai.test.ok", { ms: r.latency_ms, cost: usd(r.cost_usd), model: r.model }) : r.message }); onChanged(); },
    onError: (e) => setTest({ ok: false, message: e.message }),
  });
  const choice = (id: string) => p.model_choices.find((m) => m.id === id);
  const askChoice = choice(draft.models.ask);
  const canRun = p.key_set && !dirty;
  return (
    <Card title={<span className="inline-flex flex-wrap items-center gap-2">{p.title}{p.is_default && <Badge tone="ok">{t("ai.isDefault")}</Badge>}</span>}
      description={t("ai.provider.line", { auth: p.auth, checked: p.verified_on })}
      actions={<Badge tone={p.enabled ? "ok" : "neutral"}>{p.enabled ? t("ai.on") : t("ai.off")}</Badge>}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (dirty && editable && !save.isPending) { setProblem(null); save.mutate(undefined); } }}>
        <fieldset disabled={!editable} className="space-y-3">
          <label className="flex items-center gap-2 text-sm font-medium">
            <input type="checkbox" checked={draft.enabled} onChange={(e) => set({ ...draft, enabled: e.target.checked })} />
            {t("ai.enable")}
          </label>
          <Field label={t("ai.key.label")} hint={t("ai.key.hint")}>
            <div className="flex gap-2">
              <Input type="password" autoComplete="off" value={draft.apiKey} disabled={draft.clearKey}
                placeholder={p.key_set ? t("ai.key.saved", { last4: maskedKey(p.key_last4) }) : t("ai.key.none")}
                onChange={(e) => set({ ...draft, apiKey: e.target.value })} />
              {p.key_set && <Button type="button" size="sm" variant="ghost" onClick={() => set({ ...draft, clearKey: !draft.clearKey })}>{draft.clearKey ? t("ai.key.keep") : t("ai.key.remove")}</Button>}
            </div>
          </Field>
          <div className="grid gap-3 sm:grid-cols-3">
            {FEATURES.map((f) => (
              <Field key={f} label={t(`ai.feature.${f}`)} hint={t(`ai.feature.${f}Hint`)}>
                <Select value={draft.models[f]} onChange={(e) => set({ ...draft, models: { ...draft.models, [f]: e.target.value } })}>
                  {p.model_choices.map((m) => (
                    <option key={m.id} value={m.id}>{m.title}{m.input_per_mtok !== null ? ` — ${usd(m.input_per_mtok)} / ${usd(m.output_per_mtok)}` : ` — ${t("ai.price.unknown")}`}</option>
                  ))}
                </Select>
                <ModelNote choice={choice(draft.models[f])} />
              </Field>
            ))}
          </div>
          <p className="text-xs text-muted">{t("ai.price.perMillion")} {p.price_source && t("ai.price.updated", { date: p.prices_updated })}</p>
          {askChoice && askChoice.input_per_mtok === null && <Alert tone="warn">{t("ai.price.unknownWarn")}</Alert>}
          <Field label={t("ai.baseUrl.label")} hint={t("ai.baseUrl.hint", { url: p.default_base_url })}>
            <Input value={draft.baseUrl} maxLength={300} placeholder={p.default_base_url} onChange={(e) => set({ ...draft, baseUrl: e.target.value })} />
          </Field>
          <div>
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" className="mt-1" checked={draft.termsAcknowledged} onChange={(e) => set({ ...draft, termsAcknowledged: e.target.checked })} />
              <span>{t("ai.terms.check", { provider: p.title })}</span>
            </label>
            <p className="ml-6 text-xs text-muted">
              {p.terms_ack_at ? t("ai.terms.who", { who: p.terms_ack_by ?? "", when: formatDate(p.terms_ack_at) }) : overview.production ? t("ai.terms.requiredProduction") : t("ai.terms.optional")}
              {p.terms_url && <> · <a className="underline" href={p.terms_url} target="_blank" rel="noreferrer">{t("ai.terms.read")}</a></>}
            </p>
          </div>
        </fieldset>
        <p className="text-xs text-muted">
          {p.live_models_at ? t("ai.live.at", { when: formatDate(p.live_models_at) }) : t("ai.live.never")}
          {p.last_tested_at && ` · ${t(p.last_test_ok ? "ai.test.lastOk" : "ai.test.lastBad", { when: formatDate(p.last_tested_at) })}`}
        </p>
        {problem && <Alert tone="bad">{problem}</Alert>}
        {test && <Alert tone={test.ok ? "ok" : "bad"}>{test.message}</Alert>}
        {editable && (
          <div className="flex flex-wrap justify-end gap-2">
            <Button type="button" variant="ghost" size="sm" loading={refresh.isPending} disabled={!canRun} onClick={() => refresh.mutate(undefined)}>{t("ai.refresh")}</Button>
            <Button type="button" variant="secondary" size="sm" loading={probe.isPending} disabled={!canRun} onClick={() => { setTest(null); probe.mutate(undefined); }}>{t("ai.test.button")}</Button>
            <Button type="button" variant="secondary" size="sm" disabled={!canRun} onClick={() => setDialog("quality")}>{t("ai.quality.button")}</Button>
            {p.enabled && p.key_set && !p.is_default && <Button type="button" variant="secondary" size="sm" disabled={dirty} onClick={() => setDialog("default")}>{t("ai.default.make")}</Button>}
            <Button type="submit" size="sm" loading={save.isPending} disabled={!dirty}>{t("ai.save")}</Button>
          </div>
        )}
      </form>
      {dialog === "default" && <DefaultDialog provider={p.name} title={p.title} onClose={() => setDialog(null)} onDone={onChanged} />}
      {dialog === "quality" && <QualityDialog provider={p.name} model={draft.models.ask} onClose={() => setDialog(null)} />}
    </Card>
  );
}

function ModelNote({ choice }: { choice: AiProvider["model_choices"][number] | undefined }) {
  const { t } = useTranslation("operator");
  if (!choice) return null;
  return (
    <div className="mt-1 flex flex-wrap items-center gap-1">
      {choice.tiers.map((tier) => <Badge key={tier} tone={TIER_TONE[tier] ?? "neutral"}>{t(`ai.tier.${tier}`)}</Badge>)}
      {choice.live === false && <Badge tone="warn">{t("ai.notLive")}</Badge>}
      {choice.price_overridden && <Badge tone="info">{t("ai.priceOverridden")}</Badge>}
    </div>
  );
}
