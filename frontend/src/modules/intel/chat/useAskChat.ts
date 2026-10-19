import { useCallback, useEffect, useRef, useState } from "react";

import type { AskSource } from "../logic";
import { askStream, type StreamEvent } from "./sse";

/** One line of the chat: what the person said, or what Ziira is saying (and how far it has got). */
export interface ChatMessage {
  id: string;
  role: "user" | "ziira";
  text: string;
  /** Ziira's lines only. waiting: nothing to show yet; streaming: text is arriving; done; stopped: the person stopped it; error. */
  state: "waiting" | "streaming" | "done" | "stopped" | "error";
  /** What Ziira is doing right now, in plain words (gone once the answer starts). */
  status?: string;
  sources?: AskSource[];
  flagged?: boolean;
  capped?: boolean;
  /** Plain words about what went wrong, and why (a reason code the screen can act on). */
  error?: string;
  reason?: string;
  /** The question this answers (for Try again). */
  question?: string;
  /** True for a line that arrived in this visit, so it types out; lines restored from the tab's memory appear at once. */
  fresh?: boolean;
}

const KEY = "ziira.askChat";
interface Saved { messages: ChatMessage[]; sessionId?: string }

function restore(): Saved {
  try {
    const saved = JSON.parse(sessionStorage.getItem(KEY) ?? "null") as Saved | null;
    if (!saved || !Array.isArray(saved.messages)) return { messages: [] };
    // A line that was still being written when the page went away is shown as stopped.
    return { sessionId: saved.sessionId, messages: saved.messages.map((m) => ({ ...m, fresh: false, state: m.state === "waiting" || m.state === "streaming" ? "stopped" : m.state })) };
  } catch { return { messages: [] }; }
}
function remember(saved: Saved): void {
  try {
    if (saved.messages.length === 0) sessionStorage.removeItem(KEY);
    else sessionStorage.setItem(KEY, JSON.stringify({ sessionId: saved.sessionId, messages: saved.messages.slice(-30) }));
  } catch { /* not remembered */ }
}

export interface ChatOptions {
  companyId?: string;
  language: "en" | "sw";
  /** Called when a refusal says the assistant cannot be used (so the screen can show why). */
  onRefused?: () => void;
  /** Starts the stream; replaced in tests. */
  stream?: typeof askStream;
}

/**
 * The state of the Ask Ziira chat: your lines at once, Ziira's line filling in as events arrive, stop, try again, and the
 * conversation kept for this browser session. Only one question is in flight at a time.
 */
export function useAskChat({ companyId, language, onRefused, stream = askStream }: ChatOptions) {
  const initial = useRef<Saved>();
  initial.current ??= restore();
  const [messages, setMessages] = useState<ChatMessage[]>(initial.current.messages);
  const [sessionId, setSessionId] = useState<string | undefined>(initial.current.sessionId);
  const controller = useRef<AbortController>();
  const busy = messages.some((m) => m.role === "ziira" && (m.state === "waiting" || m.state === "streaming"));

  useEffect(() => { remember({ messages, sessionId }); }, [messages, sessionId]);
  useEffect(() => () => controller.current?.abort(), []);

  const patch = useCallback((id: string, change: Partial<ChatMessage> | ((m: ChatMessage) => Partial<ChatMessage>)) =>
    setMessages((all) => all.map((m) => (m.id === id ? { ...m, ...(typeof change === "function" ? change(m) : change) } : m))), []);

  const handle = useCallback((id: string, e: StreamEvent) => {
    const text = typeof e.data.text === "string" ? e.data.text : "";
    switch (e.event) {
      case "status": patch(id, (m) => (m.state === "waiting" ? { status: text } : {})); break;
      case "text": patch(id, (m) => ({ text: m.text + text, state: "streaming", status: undefined })); break;
      case "sources": patch(id, { sources: (e.data.sources as AskSource[] | undefined) ?? [] }); break;
      case "done": patch(id, { state: "done", status: undefined, flagged: e.data.flagged === true, capped: !!e.data.capped }); break;
      case "error": patch(id, { state: "error", status: undefined, error: String(e.data.message ?? ""), reason: String(e.data.reason ?? "") }); break;
      default: break;
    }
  }, [patch]);

  const run = useCallback(async (id: string, question: string, session: string | undefined) => {
    const abort = new AbortController();
    controller.current = abort;
    let finished = false;
    try {
      for await (const e of stream({ question, company_id: companyId, session_id: session, language }, abort.signal)) {
        if (abort.signal.aborted) break;
        if (e.event === "done") { finished = true; if (typeof e.data.session_id === "string") setSessionId(e.data.session_id); }
        if (e.event === "error") { finished = true; onRefused?.(); }
        handle(id, e);
      }
      if (!finished && !abort.signal.aborted) patch(id, { state: "error", status: undefined, reason: "connection", error: "" });
    } catch {
      if (!abort.signal.aborted) patch(id, { state: "error", status: undefined, reason: "connection", error: "" });
    } finally {
      if (controller.current === abort) controller.current = undefined;
    }
  }, [companyId, language, stream, handle, patch, onRefused]);

  const send = useCallback((raw: string): boolean => {
    const question = raw.trim();
    if (!question || busy) return false;
    const stamp = crypto.randomUUID();
    setMessages((all) => [...all, { id: `u-${stamp}`, role: "user", text: question, state: "done" },
      { id: `z-${stamp}`, role: "ziira", text: "", state: "waiting", question, fresh: true }]);
    void run(`z-${stamp}`, question, sessionId);
    return true;
  }, [busy, run, sessionId]);

  /** Stop the question in flight: what has been written stays, marked as stopped. */
  const stop = useCallback(() => {
    controller.current?.abort();
    setMessages((all) => all.map((m) => (m.role === "ziira" && (m.state === "waiting" || m.state === "streaming") ? { ...m, state: "stopped", status: undefined } : m)));
  }, []);

  /** Ask the same question again, in place of the one that failed. */
  const retry = useCallback((id: string) => {
    const failed = messages.find((m) => m.id === id);
    if (!failed?.question || busy) return;
    const question = failed.question;
    setMessages((all) => {
      const at = all.findIndex((m) => m.id === id);
      return all.filter((_, i) => i !== at && i !== at - 1);
    });
    send(question);
  }, [messages, busy, send]);

  const reset = useCallback(() => {
    controller.current?.abort();
    setMessages([]);
    setSessionId(undefined);
  }, []);

  return { messages, busy, send, stop, retry, reset };
}
