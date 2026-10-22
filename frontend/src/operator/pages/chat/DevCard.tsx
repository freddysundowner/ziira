import { useState } from "react";

import { Alert, Button, Card, Field, Input, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { useChange } from "../../stepUp";

/** Practice mode only (the server's ZIIRA_CHAT_FAKE=1): send a signed message from a made-up sender through the real inbound path. */
export function DevCard({ connected, onChanged }: { connected: boolean; onChanged: () => void }) {
  const { t } = useTranslation("operator");
  const [sender, setSender] = useState("254700111222");
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<{ status: number; reply: Record<string, unknown> | null; sent: Record<string, string>[] } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const run = useChange((button: string | null) => opUnwrap(opApi.POST("/api/v1/operator/chat/dev/simulate", { body: { sender, message: message || button || "", button_id: button } })), {
    onSuccess: (r) => { setResult(r); setProblem(null); onChanged(); }, onError: (e) => setProblem(e.message),
  });
  const body = result?.reply ? String(result.reply.text ?? result.reply.body ?? "") : "";
  const buttons = (result?.reply?.buttons as { id: string; title: string }[] | undefined) ?? [];
  return (
    <Card title={t("chat.dev.title")} description={t("chat.dev.intro")}>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (message.trim() && connected && !run.isPending) run.mutate(null); }}>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label={t("chat.dev.sender")}><Input value={sender} inputMode="numeric" onChange={(e) => setSender(e.target.value)} /></Field>
          <Field label={t("chat.dev.message")} className="sm:col-span-2"><Input value={message} onChange={(e) => setMessage(e.target.value)} /></Field>
        </div>
        {!connected && <Alert tone="info">{t("chat.dev.needConnection")}</Alert>}
        {problem && <Alert tone="bad">{problem}</Alert>}
        <div className="flex justify-end"><Button type="submit" size="sm" loading={run.isPending} disabled={!message.trim() || !connected}>{t("chat.dev.send")}</Button></div>
      </form>
      {result && (
        <div className="mt-3 space-y-2 text-sm" data-testid="dev-result">
          <p className="text-muted">{t("chat.dev.answered", { status: result.status })}</p>
          {body && <p className="whitespace-pre-wrap rounded-lg bg-sunken p-3">{body}</p>}
          {buttons.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {buttons.map((b) => <Button key={b.id} size="sm" variant="secondary" onClick={() => run.mutate(b.id)}>{b.title}</Button>)}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
