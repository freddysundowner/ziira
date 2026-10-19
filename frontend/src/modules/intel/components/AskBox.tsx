import { type FormEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import {
  api, Alert, Button, EmptyState, ErrorState, Field, Skeleton, Spinner, Textarea, unwrap, useCan, useCompany, useMutation, useQuery,
  useTranslation,
} from "@/sdk";

import AiBadge from "./AiBadge";
import AnswerSources from "./AnswerSources";
import { EXAMPLE_KEYS, fixableInSettings, reasonKey, type Turn } from "../logic";

/**
 * Ask Ziira: the chat-like body of the floating panel (see slots/AskFloating). The answer is written by AI from defined queries over what the
 * person may see, and says what it is based on. Disabled, over-budget and failed states each say what to do.
 */
export default function AskBox({ autoAsk }: { autoAsk?: { text: string; n: number } }) {
  const { t, i18n } = useTranslation("intel");
  const { company } = useCompany();
  const companyId = company?.id;
  const canSettings = useCan("ai.manage");
  const status = useQuery({
    enabled: !!companyId, queryKey: ["intel", "ai-status", companyId],
    queryFn: () => unwrap(api.GET("/api/v1/intel/ai/status", { params: { query: { company_id: companyId! } } })),
  });
  const [turns, setTurns] = useState<Turn[]>([]);
  const [sessionId, setSessionId] = useState<string>();
  const [question, setQuestion] = useState("");
  const input = useRef<HTMLTextAreaElement>(null);

  const patch = (id: string, change: Partial<Turn>) => setTurns((all) => all.map((turn) => (turn.id === id ? { ...turn, ...change } : turn)));
  const ask = useMutation({
    meta: { silent: true },
    mutationFn: ({ text }: { id: string; text: string }) => unwrap(api.POST("/api/v1/intel/ask", {
      body: { question: text, company_id: companyId, session_id: sessionId, language: i18n.language === "sw" ? "sw" : "en" } })),
    onSuccess: (answer, { id }) => { setSessionId(answer.session_id); patch(id, { answer }); },
    onError: (error, { id }) => { patch(id, { error: error.message }); void status.refetch(); },
  });

  const send = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || ask.isPending) return;
    const id = crypto.randomUUID();
    setTurns((all) => [...all, { id, question: trimmed }]);
    setQuestion("");
    ask.mutate({ id, text: trimmed });
  };
  const lastAuto = useRef(0);
  const ready = !!status.data?.ask_available;
  useEffect(() => {
    if (ready && autoAsk && autoAsk.n !== lastAuto.current) { lastAuto.current = autoAsk.n; send(autoAsk.text); }
  });
  const onSubmit = (e: FormEvent) => { e.preventDefault(); send(question); };
  const restart = () => { setTurns([]); setSessionId(undefined); input.current?.focus(); };

  const hint = <p className="text-sm text-muted">{t("ai.askHint")}</p>;
  if (status.error) return <ErrorState message={status.error.message} onRetry={() => void status.refetch()} />;
  if (!status.data) return <Skeleton className="h-24 w-full" />;
  if (!status.data.ask_available) {
    const reason = status.data.reason;
    return (
      <div className="space-y-3">
        {hint}
        <EmptyState title={t(`ai.unavailable.${reasonKey(reason)}`)}
          hint={fixableInSettings(reason) ? (canSettings ? undefined : t("ai.ownerCanFix")) : undefined}
          action={canSettings && fixableInSettings(reason) ? <Link className="text-sm font-medium text-brand-strong hover:underline" to="/admin/settings?tab=ai">{t("ai.openSettings")}</Link> : undefined} />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {hint}
      {turns.length > 0 && <div><Button size="sm" variant="ghost" onClick={restart}>{t("ai.newConversation")}</Button></div>}
      <div className="space-y-4">
        {turns.length === 0 ? (
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">{t("ai.examples")}</p>
            <div className="flex flex-wrap gap-2">
              {EXAMPLE_KEYS.map((key) => (
                <button key={key} type="button" onClick={() => send(t(`ai.example.${key}`))}
                  className="rounded-full border border-line px-3 py-1 text-left text-sm hover:bg-sunken">{t(`ai.example.${key}`)}</button>
              ))}
            </div>
          </div>
        ) : (
          <ol className="space-y-4" aria-live="polite">
            {turns.map((turn) => (
              <li key={turn.id} className="space-y-2">
                <p className="text-sm"><span className="font-medium">{t("ai.you")}: </span>{turn.question}</p>
                <Reply turn={turn} onRetry={() => { setTurns((all) => all.filter((x) => x.id !== turn.id)); send(turn.question); }} />
              </li>
            ))}
          </ol>
        )}
        <form onSubmit={onSubmit} className="space-y-2">
          <Field label={t("ai.questionLabel")}>
            <Textarea ref={input} rows={2} maxLength={1000} value={question} placeholder={t("ai.placeholder")} onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(question); } }} />
          </Field>
          <Button type="submit" loading={ask.isPending} disabled={!question.trim()}>{t("ai.send")}</Button>
        </form>
      </div>
    </div>
  );
}

/** The answer to one question: waiting, failed (with retry), or written, with what it is based on. */
function Reply({ turn, onRetry }: { turn: Turn; onRetry: () => void }) {
  const { t } = useTranslation("intel");
  if (turn.error) {
    return (
      <Alert tone="bad">
        <span>{t("ai.error", { message: turn.error })} </span>
        <button type="button" className="font-medium underline" onClick={onRetry}>{t("ai.retry")}</button>
      </Alert>
    );
  }
  if (!turn.answer) return <p className="inline-flex items-center gap-2 text-sm text-muted"><Spinner className="h-4 w-4" />{t("ai.thinking")}</p>;
  const a = turn.answer;
  return (
    <div className="rounded-lg bg-sunken/60 p-3">
      <p className="mb-1 flex flex-wrap items-center gap-2 text-xs font-semibold text-muted">{t("ai.answerLabel")}<AiBadge /></p>
      <p className="whitespace-pre-wrap text-sm">{a.answer}</p>
      {a.flagged && <Alert tone="warn" className="mt-2">{t("ai.checkFigures")}</Alert>}
      {a.capped && <p className="mt-2 text-xs text-muted">{t("ai.capped")}</p>}
      <AnswerSources sources={a.sources} />
    </div>
  );
}
