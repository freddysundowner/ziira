import { useState } from "react";

import { Alert, Badge, Button, Card, Field, Input, Textarea, toast, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { useChange } from "../../stepUp";
import { digits, type ChatOverview } from "./logic";

type Preview = { text: string; buttons: { id: string; title: string }[]; outcome: string; lang: string };

/** Try it: the reply as the phone would show it, nothing sent. And one real test message to a number the owner types. */
export function TryCard({ overview: o, editable }: { overview: ChatOverview; editable: boolean }) {
  const { t } = useTranslation("operator");
  const [message, setMessage] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [to, setTo] = useState("");
  const [sent, setSent] = useState<string | null>(null);
  const [sendProblem, setSendProblem] = useState<string | null>(null);

  const ask = useChange(() => opUnwrap(opApi.POST("/api/v1/operator/chat/try", { body: { message } })), {
    onSuccess: (r) => { setPreview(r); setProblem(null); }, onError: (e) => setProblem(e.message),
  });
  const send = useChange(() => opUnwrap(opApi.POST("/api/v1/operator/chat/test-message", { body: { to } })), {
    onSuccess: (r) => { setSent(r.to); setSendProblem(null); toast(t("chat.try.sentToast"), "ok"); }, onError: (e) => { setSent(null); setSendProblem(e.message); },
  });
  return (
    <Card title={t("chat.try.title")} description={t("chat.try.intro")}>
      <div className="space-y-5">
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (message.trim() && !ask.isPending) ask.mutate(undefined); }}>
          <Field label={t("chat.try.question")}>
            <Textarea rows={2} maxLength={500} value={message} placeholder={t("chat.try.placeholder")} onChange={(e) => { setMessage(e.target.value); setProblem(null); }} />
          </Field>
          <div className="flex justify-end"><Button type="submit" size="sm" loading={ask.isPending} disabled={!message.trim() || !editable}>{t("chat.try.ask")}</Button></div>
        </form>
        {problem && <Alert tone="bad">{problem}</Alert>}
        {preview && (
          <div aria-label={t("chat.try.preview")} className="max-w-md space-y-2 rounded-2xl rounded-tl-sm bg-sunken p-3 text-sm shadow-sm" data-testid="preview">
            <p className="whitespace-pre-wrap break-words">{preview.text}</p>
            {preview.buttons.length > 0 && (
              <div className="flex flex-col gap-1 border-t border-line pt-2">
                {preview.buttons.map((b) => <span key={b.id} className="rounded-lg bg-surface px-3 py-1.5 text-center font-medium text-brand">{b.title}</span>)}
              </div>
            )}
            <p className="text-xs text-muted"><Badge tone="neutral">{t(`chat.try.outcomes.${preview.outcome}`, { defaultValue: preview.outcome })}</Badge> {t("chat.try.notSent")}</p>
          </div>
        )}
        {editable && (
          <form className="space-y-3 border-t border-line pt-4" onSubmit={(e) => { e.preventDefault(); if (digits(to).length >= 8 && !send.isPending) send.mutate(undefined); }}>
            <p className="text-sm font-medium">{t("chat.try.testTitle")}</p>
            <p className="text-sm text-muted">{t("chat.try.testHint")}</p>
            <div className="flex flex-wrap items-end gap-2">
              <Field label={t("chat.try.to")} className="min-w-64 flex-1"><Input value={to} inputMode="tel" placeholder="+44 7700 900123" onChange={(e) => { setTo(e.target.value); setSent(null); setSendProblem(null); }} /></Field>
              <Button type="submit" variant="secondary" size="sm" loading={send.isPending} disabled={digits(to).length < 8 || o.connection.state !== "connected"}>{t("chat.try.send")}</Button>
            </div>
            {sent && <Alert tone="ok">{t("chat.try.sent", { to: sent })}</Alert>}
            {sendProblem && <Alert tone="bad">{sendProblem}</Alert>}
          </form>
        )}
      </div>
    </Card>
  );
}
