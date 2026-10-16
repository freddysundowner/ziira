import { useState } from "react";

import {
  api, Alert, Badge, Button, Card, Checkbox, ConfirmDialog, DataTable, EmptyState, ErrorState, Field, formatDate, humanise, NumberInput, Pager,
  SkeletonRows, Switch, toast, unwrap, useMutation, useQuery, useQueryClient, usePagedList, useTranslation,
} from "@/sdk";

import { type AiCall, type AiSettings, blockedReason, needsFreshConsent, parseLimit, tokens, usedPercent } from "./ai/model";

/** Settings > AI assistant: the consent an Owner gives, what it may do, its monthly limit and use, and the request log. */
export default function AiTab({ companyId }: { companyId: string | undefined }) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const key = ["ai-settings", companyId];
  const settings = useQuery({
    enabled: !!companyId, queryKey: key,
    queryFn: () => unwrap(api.GET("/api/v1/intel/ai/settings", { params: { query: { company_id: companyId! } } })),
  });
  const change = useMutation({
    mutationFn: (body: { enabled?: boolean; accept_version?: string; language?: "en" | "sw"; explanations?: boolean; auto_explain?: boolean; ask?: boolean; monthly_token_limit?: number }) =>
      unwrap(api.PUT("/api/v1/intel/ai/settings", { body: { company_id: companyId!, ...body, language: body.language ?? "en" } })),
    onSuccess: (data) => { qc.setQueryData(key, data); void qc.invalidateQueries({ queryKey: ["intel", "ai-status"] }); },
  });

  if (!companyId) return <EmptyState title={t("ai.noCompany")} />;
  if (settings.error) return <ErrorState message={settings.error.message} onRetry={() => void settings.refetch()} />;
  const s = settings.data;
  if (!s) return <SkeletonRows rows={6} cols={2} />;

  return (
    <div className="space-y-4">
      <Card title={<span className="inline-flex items-center gap-2">{t("ai.title")}<Badge tone={s.enabled ? "ok" : "neutral"}>{s.enabled ? t("ai.statusOn") : t("ai.statusOff")}</Badge></span>}
        description={s.enabled ? t("ai.hintOn") : t("ai.hint")}>
        <div className="space-y-3">
          <p className="text-sm text-muted">{t("ai.provider", { provider: s.provider_label || s.provider, model: s.model || "—" })}</p>
          {!s.configured && <Alert tone="warn">{t("ai.notConfigured")}</Alert>}
          {s.configured && !s.terms_confirmed && <Alert tone="warn">{t("ai.termsUnconfirmed")}</Alert>}
          {needsFreshConsent(s) && <Alert tone="warn">{t("ai.consentOutdated")}</Alert>}
          {s.enabled ? <SwitchOff busy={change.isPending} onConfirm={() => change.mutateAsync({ enabled: false }).then(() => toast(t("ai.switchedOff"), "ok"))} /> : null}
        </div>
      </Card>
      {s.enabled ? (
        <>
          <Uses settings={s} busy={change.isPending} onChange={(b) => change.mutate(b)} />
          <Budget settings={s} busy={change.isPending} onSave={(n) => change.mutateAsync({ monthly_token_limit: n }).then(() => toast(t("ai.budgetSaved"), "ok"))} />
          <History settings={s} />
          <CallLog companyId={companyId} />
        </>
      ) : (
        <Consent settings={s} busy={change.isPending} onAgree={(language) => change.mutateAsync({ enabled: true, accept_version: s.consent_version, language }).then(() => toast(t("ai.switchedOn"), "ok"))} />
      )}
    </div>
  );
}

function SwitchOff({ busy, onConfirm }: { busy: boolean; onConfirm: () => Promise<unknown> }) {
  const { t } = useTranslation("kernel");
  const [asking, setAsking] = useState(false);
  return (
    <>
      <Button variant="secondary" onClick={() => setAsking(true)}>{t("ai.switchOff")}</Button>
      <ConfirmDialog open={asking} onClose={() => setAsking(false)} busy={busy} danger title={t("ai.switchOffTitle")} confirmLabel={t("ai.switchOff")}
        message={t("ai.switchOffAsk")} onConfirm={() => void onConfirm().finally(() => setAsking(false))} />
    </>
  );
}

/** What is sent and not, then the agreement. Switching on is only possible after reading and ticking the box. */
function Consent({ settings, busy, onAgree }: { settings: AiSettings; busy: boolean; onAgree: (language: "en" | "sw") => Promise<unknown> }) {
  const { t, i18n } = useTranslation("kernel");
  const [agreed, setAgreed] = useState(false);
  const language = i18n.language === "sw" ? "sw" : "en";
  const bullets = (prefix: string, keys: string[]) => <ul className="list-disc space-y-1 pl-5 text-sm">{keys.map((k) => <li key={k}>{t(`${prefix}.${k}`)}</li>)}</ul>;
  const blocked = !settings.configured;
  return (
    <Card title={t("ai.consentTitle")} description={t("ai.consentVersion", { version: settings.consent_version })}>
      <div className="space-y-4">
        <section><h3 className="mb-1 text-sm font-semibold">{t("ai.whatItDoes")}</h3>{bullets("ai.does", ["explain", "rank", "ask"])}</section>
        <section><h3 className="mb-1 text-sm font-semibold">{t("ai.sentTitle")}</h3>{bullets("ai.sent", ["facts", "names", "answers", "people"])}</section>
        <section><h3 className="mb-1 text-sm font-semibold">{t("ai.notSentTitle")}</h3><p className="text-sm">{t("ai.notSent")}</p></section>
        <section><h3 className="mb-1 text-sm font-semibold">{t("ai.guardsTitle")}</h3>{bullets("ai.guards", ["figures", "label", "scope", "log", "training"])}</section>
        <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg border border-line bg-sunken/60 p-3 font-sans text-xs" tabIndex={0} aria-label={t("ai.consentTitle")}>
          {settings.consent_text[language] ?? settings.consent_text.en}
        </pre>
        <Field label="">
          <Checkbox label={t("ai.consentRead")} checked={agreed} disabled={blocked} onChange={(e) => setAgreed(e.target.checked)} />
        </Field>
        <Button loading={busy} disabled={!agreed || blocked} onClick={() => void onAgree(language)}>{t("ai.switchOn")}</Button>
        <ConsentHistory settings={settings} />
      </div>
    </Card>
  );
}

function ConsentHistory({ settings }: { settings: AiSettings }) {
  const { t } = useTranslation("kernel");
  if (settings.consents.length === 0) return null;
  return (
    <section>
      <h3 className="mb-1 text-sm font-semibold">{t("ai.history")}</h3>
      <ul className="space-y-0.5 text-xs text-muted">
        {settings.consents.map((c, i) => (
          <li key={i}>{t(c.action === "granted" ? "ai.agreed" : "ai.withdrawn", { who: c.user_name ?? "—", date: formatDate(c.created_at, true), version: c.text_version })}</li>
        ))}
      </ul>
    </section>
  );
}

function History({ settings }: { settings: AiSettings }) {
  return <Card><ConsentHistory settings={settings} /></Card>;
}

function Uses({ settings, busy, onChange }: { settings: AiSettings; busy: boolean; onChange: (b: { explanations?: boolean; auto_explain?: boolean; ask?: boolean }) => void }) {
  const { t } = useTranslation("kernel");
  const row = (label: string, checked: boolean, set: (v: boolean) => void, disabled = false) => (
    <div className="flex items-center justify-between gap-4"><span className="text-sm">{label}</span><Switch label={label} checked={checked} disabled={busy || disabled} onChange={set} /></div>
  );
  return (
    <Card title={t("ai.useTitle")}>
      <div className="max-w-xl space-y-3">
        {row(t("ai.useExplanations"), settings.explanations, (v) => onChange({ explanations: v }))}
        {row(t("ai.useAuto"), settings.auto_explain, (v) => onChange({ auto_explain: v }), !settings.explanations)}
        {row(t("ai.useAsk"), settings.ask, (v) => onChange({ ask: v }))}
      </div>
    </Card>
  );
}

function Budget({ settings, busy, onSave }: { settings: AiSettings; busy: boolean; onSave: (n: number) => Promise<unknown> }) {
  const { t } = useTranslation("kernel");
  const [text, setText] = useState(String(settings.monthly_token_limit));
  const parsed = parseLimit(text);
  const percent = usedPercent(settings.tokens_used, settings.monthly_token_limit);
  return (
    <Card title={t("ai.budgetTitle")}>
      <div className="max-w-xl space-y-4">
        <div>
          <p className="text-sm">{t("ai.usedOf", { used: tokens(settings.tokens_used), limit: tokens(settings.monthly_token_limit) })}</p>
          <div className="mt-1 h-2 overflow-hidden rounded-full bg-line" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
            <div className={percent >= 90 ? "h-full bg-bad" : "h-full bg-brand"} style={{ width: `${percent}%` }} />
          </div>
          <p className="mt-1 text-xs text-muted">{t("ai.calls", { count: settings.calls })}</p>
        </div>
        <Field label={t("ai.budgetLabel")} hint={t("ai.budgetHint")}>
          <NumberInput value={text} onChange={setText} inputMode="numeric" />
        </Field>
        <Button loading={busy} disabled={parsed === null || parsed === settings.monthly_token_limit} onClick={() => parsed !== null && void onSave(parsed)}>{t("ai.budgetSave")}</Button>
        {settings.usage.length > 1 && (
          <table className="w-full text-left text-xs">
            <thead><tr className="border-b border-line text-muted"><th className="py-1 font-medium">{t("ai.usageMonth")}</th><th className="py-1 text-right font-medium">{t("ai.usageTokens")}</th><th className="py-1 text-right font-medium">{t("ai.usageCalls")}</th></tr></thead>
            <tbody>{settings.usage.map((u) => (
              <tr key={u.month} className="border-b border-line/60 last:border-0"><td className="py-1">{u.month.slice(0, 7)}</td><td className="tnum py-1 text-right">{tokens(u.input_tokens + u.output_tokens)}</td><td className="tnum py-1 text-right">{u.calls}</td></tr>
            ))}</tbody>
          </table>
        )}
      </div>
    </Card>
  );
}

/** The record of every request to the provider (and every refusal to make one). Owners only. */
function CallLog({ companyId }: { companyId: string }) {
  const { t } = useTranslation("kernel");
  const list = usePagedList(["ai-calls", companyId], (limit, offset) =>
    unwrap(api.GET("/api/v1/intel/ai/calls", { params: { query: { company_id: companyId, limit, offset } } })), 20);
  // Tool names are translated by the module that owns Ask Ziira (intel); any other name reads as words.
  const toolLabel = (name: string) => (name ? t(`intel:ai.tool.${name}`, { defaultValue: humanise(name.split("_").slice(1).join("_")) }) : "");
  const outcome = (c: AiCall) => {
    const reason = blockedReason(c.status);
    if (reason) return <Badge tone="warn">{t("ai.blocked", { reason: t(`ai.reason.${reason}`, { defaultValue: humanise(reason) }) })}</Badge>;
    return <Badge tone={c.status === "ok" ? "ok" : "bad"}>{t(`ai.status.${c.status}`, { defaultValue: humanise(c.status) })}</Badge>;
  };
  return (
    <Card title={t("ai.logTitle")} description={t("ai.logHint")} flush>
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(c) => c.id} dense
        empty={{ title: t("ai.logNone"), hint: t("ai.logNoneHint") }}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
        columns={[
          { header: t("ai.logWhen"), cell: (c) => formatDate(c.created_at, true) },
          { header: t("ai.logWho"), hideBelow: "sm", cell: (c) => c.user_name ?? t("ai.system") },
          { header: t("ai.logWhat"), cell: (c) => t(`ai.purpose.${c.purpose}`, { defaultValue: humanise(c.purpose) }) },
          { header: t("ai.logStatus"), cell: outcome },
          { header: t("ai.logTools"), hideBelow: "md", cell: (c) => c.tool_calls.map((x) => toolLabel(String((x as { name?: string }).name ?? ""))).filter(Boolean).join(", ") || "—" },
          { header: t("ai.logTokens"), align: "right", hideBelow: "sm", cell: (c) => <span className="tnum">{tokens(c.input_tokens + c.output_tokens)}</span> },
        ]} />
    </Card>
  );
}
