import { Sparkles } from "lucide-react";

import { Alert, cx, useTranslation } from "@/sdk";

import { type ChatMessage } from "../chat/useAskChat";
import { formatAnswer } from "../chat/format";
import { useReveal } from "../chat/reveal";
import AiBadge from "./AiBadge";
import AnswerSources from "./AnswerSources";

/** Ziira's little round badge beside its lines. */
export function Avatar() {
  return <span aria-hidden="true" className="mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand/10 text-brand"><Sparkles className="h-4 w-4" /></span>;
}

/** Three dots, one after the other; still when the person asked for less motion. */
export function TypingDots() {
  const { t } = useTranslation("intel");
  return (
    <span role="img" aria-label={t("ai.typing")} className="inline-flex items-center gap-1 py-1.5">
      {[0, 150, 300].map((delay) => (
        <span key={delay} style={{ animationDelay: `${delay}ms` }} className="h-1.5 w-1.5 rounded-full bg-muted motion-safe:animate-bounce" />
      ))}
    </span>
  );
}

/** What the person said: on the right. */
export function UserBubble({ message }: { message: ChatMessage }) {
  return (
    <li className="flex justify-end">
      <p className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-brand px-3.5 py-2 text-sm text-white">{message.text}</p>
    </li>
  );
}

/** What Ziira says: on the left, with its badge. Waiting shows the dots and what it is doing; then the answer types out. */
export function ZiiraBubble({ message, onRetry }: { message: ChatMessage; onRetry: () => void }) {
  const { t } = useTranslation("intel");
  const animate = !!message.fresh;
  const { shown, typing, skip } = useReveal(message.text, animate);
  const finished = message.state === "done" || message.state === "stopped";
  return (
    <li className="flex items-start gap-2">
      <Avatar />
      <div className="min-w-0 max-w-[88%] space-y-1">
        <p className="flex items-center gap-1.5 text-xs font-semibold text-muted">{t("ai.answerLabel")}<AiBadge short /></p>
        {message.state === "waiting" && (
          <div className="rounded-2xl rounded-tl-md bg-sunken px-3.5 py-2">
            <TypingDots />
            {message.status && <p role="status" className="text-xs text-muted">{message.status}…</p>}
          </div>
        )}
        {message.text && (
          <div className="rounded-2xl rounded-tl-md bg-sunken px-3.5 py-2">
            {/* The words appear a few at a time; a screen reader gets the whole answer once it is complete, not every word. */}
            <p aria-hidden={animate || undefined} onClick={typing ? skip : undefined} className={cx("whitespace-pre-wrap break-words text-sm", typing && "cursor-pointer")}>{formatAnswer(shown)}</p>
            {animate && finished && <p className="sr-only">{message.text}</p>}
            {typing && <button type="button" onClick={skip} className="mt-1 text-xs text-muted underline hover:text-ink">{t("ai.showAll")}</button>}
          </div>
        )}
        {message.state === "stopped" && <p className="text-xs text-muted">{t("ai.stopped")}</p>}
        {message.state === "error" && (
          <Alert tone="bad">
            <span>{message.error || t("ai.connectionLost")} </span>
            {message.question && message.reason !== "not_enabled" && <button type="button" className="font-medium underline" onClick={onRetry}>{t("ai.retry")}</button>}
          </Alert>
        )}
        {message.state === "done" && !typing && (
          <>
            {message.flagged && <Alert tone="warn">{t("ai.checkFigures")}</Alert>}
            {message.capped && <p className="text-xs text-muted">{t("ai.capped")}</p>}
            {(message.sources?.length ?? 0) > 0 && (
              <details className="text-sm">
                <summary className="cursor-pointer text-xs font-medium text-brand-strong hover:underline">{t("ai.howIKnow")}</summary>
                <AnswerSources sources={message.sources ?? []} />
              </details>
            )}
          </>
        )}
      </div>
    </li>
  );
}
