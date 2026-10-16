import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Alert, Badge, Button, Card, ErrorState, Field, formatDate, Input, PageHeader, Skeleton, toast, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../client";
import { useOperatorCan, useOperatorMe } from "../me";
import { useChange } from "../stepUp";
import { MailLog } from "./email/MailLog";
import { ProviderCard } from "./email/ProviderCard";

const KEY = ["operator", "email"];

/** Platform > Email: where the platform's own mail (sign-up, password reset, billing) is set up, tested and made live. */
export default function EmailPage() {
  const { t } = useTranslation("operator");
  const editable = useOperatorCan("platform.settings");
  const me = useOperatorMe();
  const queryClient = useQueryClient();
  const page = useQuery({ queryKey: KEY, queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/email")) });
  const [testTo, setTestTo] = useState("");
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [checks, setChecks] = useState<{ level: string; message: string }[] | null>(null);
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["operator"] });

  const test = useChange((provider: string | null) => opUnwrap(opApi.POST("/api/v1/operator/email/test", { body: { provider, to: testTo.trim() || null } })), {
    onSuccess: (r) => { setResult({ ok: r.ok, message: r.ok ? t("email.test.ok") : r.message }); refresh(); },
    onError: (e) => setResult({ ok: false, message: e.message }),
  });
  const check = useChange(() => opUnwrap(opApi.POST("/api/v1/operator/email/check", { params: { query: {} } })), { onSuccess: setChecks });
  const move = useChange(() => opUnwrap(opApi.POST("/api/v1/operator/email/move-from-environment")), { onSuccess: () => { toast(t("email.moved"), "ok"); refresh(); } });
  const revert = useChange(() => opUnwrap(opApi.PUT("/api/v1/operator/email/active", { body: { provider: "" } })), { onSuccess: () => { toast(t("email.provider.reverted"), "ok"); refresh(); } });

  if (page.isPending) return <Skeleton className="h-64 w-full" />;
  if (page.isError) return <ErrorState title={t("email.loadFailed")} message={page.error.message} onRetry={() => void page.refetch()} />;
  const d = page.data;
  const s = d.status;
  return (
    <div className="space-y-5">
      <PageHeader title={t("email.title")} description={t("email.intro")} />
      {!editable && <Alert tone="info">{t("email.readOnly")}</Alert>}

      <Card>
        <div className="flex flex-wrap items-center gap-3">
          <Badge tone={s.working ? "ok" : "warn"}>{s.working ? t("email.status.working") : t("email.status.notWorking")}</Badge>
          <span className="text-sm">{t(`email.status.source.${s.source}`)}{s.provider ? ` (${s.provider})` : ""}</span>
        </div>
        <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-3">
          <div><dt className="text-muted">{t("email.status.lastSuccess")}</dt><dd>{s.last_success_at ? formatDate(s.last_success_at, true) : t("email.status.never")}</dd></div>
          <div><dt className="text-muted">{t("email.status.failures")}</dt><dd className="tnum">{s.failures_24h}</dd></div>
          <div><dt className="text-muted">{t("email.status.lastTest")}</dt><dd>{d.last_test ? `${d.last_test.ok ? t("email.test.ok") : d.last_test.message} (${formatDate(d.last_test.at, true)})` : t("email.status.never")}</dd></div>
        </dl>
        {editable && (
          <div className="mt-3 flex flex-wrap gap-2">
            {d.environment && <Button size="sm" variant="secondary" loading={move.isPending} onClick={() => move.mutate(undefined)}>{t("email.move")}</Button>}
            {d.source === "platform" && <Button size="sm" variant="secondary" loading={revert.isPending} onClick={() => revert.mutate(undefined)}>{t("email.provider.useEnvironment")}</Button>}
          </div>
        )}
        {d.environment && editable && <p className="mt-2 text-xs text-muted">{t("email.moveHint")}</p>}
      </Card>

      <SenderCard sender={d.sender} editable={editable} onSaved={refresh} />

      {d.providers.map((p) => (
        <ProviderCard key={`${p.name}:${p.updated_at}:${p.selected}`} provider={p} editable={editable} onChanged={refresh}
          onTest={(name) => { setResult(null); test.mutate(name); }} />
      ))}

      {editable && (
        <Card title={t("email.test.to")}>
          <div className="flex flex-wrap items-end gap-2">
            <Field label={t("email.test.to")} hint={t("email.test.toHint")} className="min-w-64 flex-1">
              <Input type="email" placeholder={me.data?.email ?? ""} value={testTo} onChange={(e) => setTestTo(e.target.value)} />
            </Field>
            <Button variant="secondary" loading={test.isPending} onClick={() => { setResult(null); test.mutate(null); }}>{t("email.provider.test")}</Button>
            <Button variant="secondary" loading={check.isPending} onClick={() => check.mutate(undefined)}>{t("email.provider.check")}</Button>
          </div>
          {result && <Alert tone={result.ok ? "ok" : "bad"} className="mt-3">{result.message}</Alert>}
          {checks && (
            <ul className="mt-3 space-y-1 text-sm" aria-label={t("email.check.title")}>
              {checks.map((c, i) => <li key={i}><Badge tone={c.level === "ok" ? "ok" : c.level === "bad" ? "bad" : c.level === "warn" ? "warn" : "info"}>{t(`email.check.${c.level}`)}</Badge> {c.message}</li>)}
            </ul>
          )}
        </Card>
      )}

      <MailLog version={d.status.last_success_at ?? d.last_test?.at ?? s.failures_24h} />
    </div>
  );
}

function SenderCard({ sender, editable, onSaved }: { sender: { from_address: string; from_name: string; reply_to: string }; editable: boolean; onSaved: () => void }) {
  const { t } = useTranslation("operator");
  const [draft, setDraft] = useState(sender);
  const [problem, setProblem] = useState<string | null>(null);
  const dirty = JSON.stringify(draft) !== JSON.stringify(sender);
  const save = useChange(() => opUnwrap(opApi.PUT("/api/v1/operator/email/sender", { body: draft })), {
    onSuccess: () => { toast(t("email.sender.saved"), "ok"); onSaved(); }, onError: (e) => setProblem(e.message),
  });
  const set = (key: keyof typeof draft, value: string) => { setDraft({ ...draft, [key]: value }); setProblem(null); };
  return (
    <Card title={t("email.sender.title")} description={t("email.sender.hint")}>
      <form className="grid gap-3 sm:grid-cols-3" onSubmit={(e) => { e.preventDefault(); if (dirty && editable && !save.isPending) save.mutate(undefined); }}>
        <fieldset disabled={!editable} className="contents">
          <Field label={t("email.sender.from")} required><Input type="email" maxLength={200} value={draft.from_address} onChange={(e) => set("from_address", e.target.value)} /></Field>
          <Field label={t("email.sender.fromName")}><Input maxLength={100} value={draft.from_name} onChange={(e) => set("from_name", e.target.value)} /></Field>
          <Field label={t("email.sender.replyTo")}><Input type="email" maxLength={200} value={draft.reply_to} onChange={(e) => set("reply_to", e.target.value)} /></Field>
        </fieldset>
        {problem && <Alert tone="bad" className="sm:col-span-3">{problem}</Alert>}
        {editable && <div className="sm:col-span-3 flex justify-end"><Button type="submit" size="sm" loading={save.isPending} disabled={!dirty}>{t("email.sender.save")}</Button></div>}
      </form>
    </Card>
  );
}
