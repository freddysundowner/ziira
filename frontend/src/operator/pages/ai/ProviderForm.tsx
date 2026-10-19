import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useEffect, useState } from "react";

import { Alert, Button, ConfirmDialog, Field, Input, Select, toast, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { type AiOverview, type AiProvider, hasKey, maskedKey, modelOptions, modelSelectValue, OTHER_MODEL, type ProviderDraft, providerDirty, bodyToUse, usd, withModel } from "../../helpers/ai";
import { useOperatorCan } from "../../me";
import { useChange } from "../../stepUp";

export interface FormState {
  draft: ProviderDraft;
  typingOther: boolean;
  replacingKey: boolean;
  cap: string;
}

/** The one calm form: key, model, spend limit, Test and Save and use. Everything else is under Details. */
export function ProviderForm({ provider: p, overview, state, setState, onChanged, onSaved, providerField, status }: {
  providerField: ReactNode; status: ReactNode; provider: AiProvider; overview: AiOverview; state: FormState; setState: (next: FormState) => void; onChanged: () => void; onSaved: () => void;
}) {
  const { t } = useTranslation("operator");
  const editable = useOperatorCan("platform.ai");
  const [problem, setProblem] = useState<string | null>(null);
  const [test, setTest] = useState<{ ok: boolean; message: string } | null>(null);
  const [removing, setRemoving] = useState(false);
  useEffect(() => { setProblem(null); setTest(null); setRemoving(false); }, [p.name]);   // the dropdown stays mounted: only the notes are reset
  const { draft, typingOther, replacingKey, cap } = state;
  const opts = modelOptions(p);
  const selectValue = modelSelectValue(p, draft.models.ask, typingOther);
  const current = p.model_choices.find((m) => m.id === draft.models.ask);
  const capChanged = cap.trim() !== (overview.monthly_cap_usd ?? "");
  const providerChanged = providerDirty(p, { ...draft, enabled: true });
  const inUse = overview.default_provider === p.name;
  const dirty = providerChanged || capChanged || !inUse;
  const keyReady = hasKey(p, draft);
  const termsNeeded = overview.production && p.terms_ack_at === null;
  const termsMissing = termsNeeded && !draft.termsAcknowledged;
  const change = (next: Partial<FormState>) => { setState({ ...state, ...next }); setProblem(null); setTest(null); };

  const switchNote = useQuery({
    queryKey: ["operator", "ai", "default-change", p.name], enabled: !inUse && overview.default_provider !== null,
    queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/ai/default-change", { params: { query: { provider: p.name } } })),
  });

  const saveProvider = () => (providerChanged || !p.enabled) ? opUnwrap(opApi.PUT("/api/v1/operator/ai/providers/{name}", { params: { path: { name: p.name } }, body: bodyToUse(p, draft) })) : Promise.resolve(null);
  const saveAndUse = useChange(async () => {
    await saveProvider();
    if (capChanged) await opUnwrap(opApi.PUT("/api/v1/operator/ai/cap", { body: { cap_usd: cap.trim() === "" ? null : cap.trim() } }));
    if (!inUse) await opUnwrap(opApi.PUT("/api/v1/operator/ai/active", { body: { provider: p.name } }));
  }, {
    onSuccess: () => { toast(t("ai.form.nowInUse", { name: p.title }), "ok"); onSaved(); },
    onError: (e) => { setProblem(e.message); onChanged(); },
  });
  const probe = useChange(async () => {
    await saveProvider();
    return opUnwrap(opApi.POST("/api/v1/operator/ai/providers/{name}/test", { params: { path: { name: p.name } } }));
  }, {
    onSuccess: (r) => { setTest(r.ok ? { ok: true, message: t("ai.form.testOk", { model: r.model, ms: r.latency_ms }) } : { ok: false, message: t("ai.form.testBad", { reason: r.message }) }); onChanged(); },
    onError: (e) => setTest({ ok: false, message: t("ai.form.testBad", { reason: e.message }) }),
  });
  const remove = useChange(() => opUnwrap(opApi.PUT("/api/v1/operator/ai/providers/{name}", { params: { path: { name: p.name } }, body: { clear_key: true } })), {
    onSuccess: () => { toast(t("ai.form.keyRemoved", { name: p.title }), "ok"); setRemoving(false); onSaved(); },
    onError: (e) => { setRemoving(false); setProblem(e.message); },
  });

  const busy = saveAndUse.isPending || probe.isPending;
  const price = current && current.input_per_mtok !== null ? t("ai.form.price", { input: usd(current.input_per_mtok), output: usd(current.output_per_mtok) }) : null;

  const modelField = (
    <div className="min-w-0 space-y-4">
        <Field label={t("ai.form.model")} hint={price ?? undefined}>
          <Select value={selectValue} onChange={(e) => {
            const v = e.target.value;
            if (v === OTHER_MODEL) change({ typingOther: true });
            else change({ typingOther: false, draft: withModel(draft, v) });
          }}>
            {opts.fast && <option value={opts.fast.id}>{t("ai.form.modelFast")}</option>}
            {opts.capable && <option value={opts.capable.id}>{t("ai.form.modelCapable")}</option>}
            <option value={OTHER_MODEL}>{t("ai.form.modelOther")}</option>
          </Select>
        </Field>
        {selectValue === OTHER_MODEL && (
          <Field label={t("ai.form.modelName")} hint={t("ai.form.modelNameHint")}>
            <Input value={draft.models.ask} maxLength={100} autoComplete="off" spellCheck={false} onChange={(e) => change({ draft: withModel(draft, e.target.value.trim()) })} />
          </Field>
        )}
    </div>
  );

  return (
    <form className="space-y-4" noValidate onSubmit={(e) => { e.preventDefault(); if (editable && keyReady && !termsMissing && !busy) { setProblem(null); saveAndUse.mutate(undefined); } }}>
      <fieldset disabled={!editable} className="grid min-w-0 gap-4 min-[900px]:grid-cols-2">
        {providerField}
        {modelField}
        <Field className="min-[900px]:col-span-2" label={t("ai.key.label")} hint={t("ai.form.keyHint")}>
          {p.key_set && !replacingKey ? (
            <div className="flex flex-wrap items-center gap-2">
              <span className="min-w-0 flex-1 rounded-lg border border-line bg-sunken px-3 py-2 text-sm" data-testid="key-saved">{t("ai.form.keySaved", { last4: maskedKey(p.key_last4) })}</span>
              <Button type="button" size="sm" variant="secondary" onClick={() => change({ replacingKey: true })}>{t("ai.form.replace")}</Button>
              <Button type="button" size="sm" variant="ghost" onClick={() => setRemoving(true)}>{t("ai.key.remove")}</Button>
            </div>
          ) : (
            <div className="flex gap-2">
              <Input type="password" autoComplete="off" autoCapitalize="off" spellCheck={false} value={draft.apiKey} placeholder={t("ai.key.none")}
                onChange={(e) => change({ draft: { ...draft, apiKey: e.target.value } })} />
              {p.key_set && <Button type="button" size="sm" variant="ghost" onClick={() => change({ replacingKey: false, draft: { ...draft, apiKey: "" } })}>{t("ai.key.keep")}</Button>}
            </div>
          )}
        </Field>
        <Field label={t("ai.form.limit")} hint={t("ai.form.limitHint", { spend: usd(overview.month_spend_usd) })}>
          <Input inputMode="decimal" value={cap} maxLength={20} placeholder={t("ai.cap.none")} onChange={(e) => change({ cap: e.target.value })} />
        </Field>
        <div className="min-w-0 self-start">{status}</div>
        {termsNeeded && (
          <label className="min-[900px]:col-span-2 flex items-start gap-2 text-sm">
            <input type="checkbox" className="mt-1" checked={draft.termsAcknowledged} onChange={(e) => change({ draft: { ...draft, termsAcknowledged: e.target.checked } })} />
            <span>{t("ai.terms.check", { provider: p.title })}</span>
          </label>
        )}
      </fieldset>
      {!inUse && switchNote.data && switchNote.data.consents_affected > 0 && <Alert tone="warn">{t("ai.form.consentsEnd", { count: switchNote.data.consents_affected })}</Alert>}
      {problem && <Alert tone="bad">{problem}</Alert>}
      {test && <Alert tone={test.ok ? "ok" : "bad"}>{test.message}</Alert>}
      {editable && (
        <div className="sticky bottom-0 -mx-4 flex flex-wrap items-center justify-between gap-2 border-t border-line bg-surface px-4 py-3">
          <p className="text-xs text-muted">{!keyReady ? t("ai.form.needKey") : termsMissing ? t("ai.terms.requiredProduction") : dirty ? t("ai.form.unsaved") : t("ai.form.upToDate")}</p>
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="secondary" loading={probe.isPending} disabled={!keyReady || busy} onClick={() => { setTest(null); probe.mutate(undefined); }}>{t("ai.form.test")}</Button>
            <Button type="submit" loading={saveAndUse.isPending} disabled={!keyReady || termsMissing || !dirty || busy}>{t("ai.form.saveAndUse")}</Button>
          </div>
        </div>
      )}
      <ConfirmDialog open={removing} onClose={() => setRemoving(false)} onConfirm={() => remove.mutate(undefined)} busy={remove.isPending} danger
        title={t("ai.form.removeTitle", { name: p.title })} message={t(inUse ? "ai.form.removeInUse" : "ai.form.removeBody")} confirmLabel={t("ai.key.remove")} />
    </form>
  );
}
