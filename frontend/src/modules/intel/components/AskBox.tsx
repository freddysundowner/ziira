import { SendHorizontal, Square } from "lucide-react";
import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api, Button, EmptyState, ErrorState, Skeleton, unwrap, useCan, useCompany, useQuery, useTranslation } from "@/sdk";

import { useAskChat } from "../chat/useAskChat";
import { EXAMPLE_KEYS, fixableInSettings, reasonKey } from "../logic";
import { Avatar, UserBubble, ZiiraBubble } from "./ChatParts";

const DRAFT_KEY = "ziira.askDraft";
const FOLLOW_UPS = ["lastWeek", "byBranch"] as const;
const NEAR_BOTTOM = 48;

function savedDraft(): string {
  try { return sessionStorage.getItem(DRAFT_KEY) ?? ""; } catch { return ""; }
}
function saveDraft(text: string) {
  try { if (text) sessionStorage.setItem(DRAFT_KEY, text); else sessionStorage.removeItem(DRAFT_KEY); } catch { /* not kept */ }
}

/**
 * Ask Ziira: the chat inside the floating panel. Your line appears at once on the right; Ziira's on the left shows dots and what it is
 * doing, then types the answer out sentence by sentence, with how it knows underneath. Fills the panel: the lines scroll, the box stays.
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
  const refetchStatus = status.refetch;
  const onRefused = useCallback(() => { void refetchStatus(); }, [refetchStatus]);
  const chat = useAskChat({ companyId, language: i18n.language === "sw" ? "sw" : "en", onRefused });
  const [draft, setDraft] = useState(savedDraft);
  const input = useRef<HTMLTextAreaElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const sticky = useRef(true);

  const change = (text: string) => { setDraft(text); saveDraft(text); };
  const send = useCallback((text: string) => {
    if (!chat.send(text)) return;
    sticky.current = true;
    change("");
    input.current?.focus();
  }, [chat]);
  const lastAuto = useRef(0);
  const ready = !!status.data?.ask_available;
  useEffect(() => {
    if (ready && autoAsk && autoAsk.n !== lastAuto.current) { lastAuto.current = autoAsk.n; send(autoAsk.text); }
  });

  // Keep the newest line in view, unless the person has scrolled up to read.
  const follow = () => { const el = scroller.current; if (el && sticky.current) el.scrollTop = el.scrollHeight; };
  const lines = chat.messages.map((m) => `${m.id}${m.text.length}${m.state}${m.status ?? ""}`).join("|");
  useEffect(follow, [lines]);
  useEffect(() => {
    const el = scroller.current;
    if (!el || typeof ResizeObserver === "undefined" || !el.firstElementChild) return;
    const watcher = new ResizeObserver(follow);    // the typing makes the lines taller without any new state
    watcher.observe(el.firstElementChild);
    return () => watcher.disconnect();
  }, [ready, chat.messages.length]);
  useEffect(() => { if (ready) input.current?.focus(); }, [ready]);
  // The box grows with what is typed, to four lines.
  useEffect(() => {
    const el = input.current;
    if (el) { el.style.height = "auto"; el.style.height = `${Math.min(el.scrollHeight, 112)}px`; }
  }, [draft, ready]);

  const onSubmit = (e: FormEvent) => { e.preventDefault(); if (chat.busy) chat.stop(); else send(draft); };

  if (status.error) return <div className="p-4"><ErrorState message={status.error.message} onRetry={() => void status.refetch()} /></div>;
  if (!status.data) return <div className="p-4"><Skeleton className="h-24 w-full" /></div>;
  if (!status.data.ask_available) {
    const reason = status.data.reason;
    return (
      <div className="space-y-3 p-4">
        <p className="text-sm text-muted">{t("ai.askHint")}</p>
        <EmptyState title={t(`ai.unavailable.${reasonKey(reason)}`)}
          hint={fixableInSettings(reason) ? (canSettings ? undefined : t("ai.ownerCanFix")) : undefined}
          action={canSettings && fixableInSettings(reason) ? <Link className="text-sm font-medium text-brand-strong hover:underline" to="/admin/settings?tab=ai">{t("ai.openSettings")}</Link> : undefined} />
      </div>
    );
  }

  const last = chat.messages[chat.messages.length - 1];
  const showFollowUps = !chat.busy && last?.role === "ziira" && last.state === "done" && !last.flagged;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div ref={scroller} onScroll={(e) => { const el = e.currentTarget; sticky.current = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM; }}
        className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        <div className="space-y-4">
          {chat.messages.length === 0 ? (
            <div className="space-y-4">
              <div className="flex items-start gap-2">
                <Avatar />
                <p className="rounded-2xl rounded-tl-md bg-sunken px-3.5 py-2 text-sm">{t("ai.askHint")}</p>
              </div>
              <div>
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">{t("ai.examples")}</p>
                <div className="flex flex-wrap gap-2">
                  {EXAMPLE_KEYS.map((key) => (
                    <button key={key} type="button" onClick={() => send(t(`ai.example.${key}`))}
                      className="rounded-full border border-line px-3 py-1 text-left text-sm hover:bg-sunken">{t(`ai.example.${key}`)}</button>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <>
              <ol role="log" aria-live="polite" aria-label={t("ai.askTitle")} className="space-y-4">
                {chat.messages.map((m) => (m.role === "user" ? <UserBubble key={m.id} message={m} /> : <ZiiraBubble key={m.id} message={m} onRetry={() => chat.retry(m.id)} />))}
              </ol>
              {showFollowUps && (
                <div className="flex flex-wrap gap-2 pl-9">
                  {FOLLOW_UPS.map((key) => (
                    <button key={key} type="button" onClick={() => send(t(`ai.followUp.${key}`))}
                      className="rounded-full border border-line px-3 py-1 text-left text-xs hover:bg-sunken">{t(`ai.followUp.${key}`)}</button>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>
      <form onSubmit={onSubmit} className="shrink-0 border-t border-line px-4 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3">
        <div className="flex items-end gap-2">
          <textarea ref={input} rows={1} maxLength={1000} value={draft} aria-label={t("ai.questionLabel")} placeholder={t("ai.placeholder")}
            onChange={(e) => change(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(draft); } }}
            className="max-h-28 min-h-[40px] w-full resize-none rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-muted hover:border-muted/50" />
          {chat.busy ? (
            <Button type="submit" variant="secondary" aria-label={t("ai.stop")} title={t("ai.stop")} className="h-10 w-10 shrink-0 !p-0"><Square className="h-4 w-4" aria-hidden="true" /></Button>
          ) : (
            <Button type="submit" aria-label={t("ai.send")} title={t("ai.send")} disabled={!draft.trim()} className="h-10 w-10 shrink-0 !p-0"><SendHorizontal className="h-4 w-4" aria-hidden="true" /></Button>
          )}
        </div>
        <div className="mt-1.5 flex items-center justify-between text-xs text-muted">
          <span>{t("ai.enterHint")}</span>
          {chat.messages.length > 0 && <button type="button" onClick={() => { chat.reset(); input.current?.focus(); }} className="hover:text-ink hover:underline">{t("ai.newConversation")}</button>}
        </div>
      </form>
    </div>
  );
}
