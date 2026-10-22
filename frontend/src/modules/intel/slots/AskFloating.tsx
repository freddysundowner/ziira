import { Sparkles, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";

import { cx, useTranslation } from "@/sdk";

import AiBadge from "../components/AiBadge";
import AskBox from "../components/AskBox";
import { ASK_ZIIRA_OPEN_EVENT } from "../public";

const KEY = "ziira.askOpen";
const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
/** Full-screen pages (the till terminal) get no floating button. */
const HIDDEN_ON = ["/pos/terminal", "/terminal", "/till"];

function wasOpen(): boolean {
  try { return sessionStorage.getItem(KEY) === "1"; } catch { return false; }
}
function remember(open: boolean) {
  try { if (open) sessionStorage.setItem(KEY, "1"); else sessionStorage.removeItem(KEY); } catch { /* not remembered */ }
}

/** The floating Ask Ziira button (bottom right) and its panel: a popover on a computer, a full-height sheet on a phone. */
export default function AskFloating() {
  const { t } = useTranslation("intel");
  const { pathname } = useLocation();
  const [open, setOpen] = useState(wasOpen);
  const [mounted, setMounted] = useState(open);   // kept alive once opened, so the conversation survives closing
  const [auto, setAuto] = useState<{ text: string; n: number }>();
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const hidden = HIDDEN_ON.some((p) => pathname === p || pathname.startsWith(`${p}/`));

  const show = useCallback((next: boolean) => {
    setOpen(next); remember(next);
    if (next) setMounted(true);
  }, []);

  useEffect(() => {
    const onOpen = (e: Event) => {
      const q = (e as CustomEvent<{ question?: string }>).detail?.question?.trim();
      if (q) setAuto((a) => ({ text: q, n: (a?.n ?? 0) + 1 }));
      show(true);
    };
    window.addEventListener(ASK_ZIIRA_OPEN_EVENT, onOpen);
    return () => window.removeEventListener(ASK_ZIIRA_OPEN_EVENT, onOpen);
  }, [show]);

  // Focus moves into the panel when it opens (unless it was restored from the tab's memory) and back to the button when it closes.
  const first = useRef(true);
  useEffect(() => {
    if (first.current) { first.current = false; if (open) return; }
    if (open) (panel.current?.querySelector<HTMLElement>("textarea") ?? panel.current)?.focus();
    else button.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); show(false); return; }
      if (e.key !== "Tab" || !panel.current || !panel.current.contains(document.activeElement)) return;
      const items = [...panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
      if (items.length === 0) return;
      const a = items[0]!, z = items[items.length - 1]!;
      if (e.shiftKey && document.activeElement === a) { e.preventDefault(); z.focus(); }
      else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, show]);

  if (hidden) return null;
  const title = t("ai.askTitle");
  return (
    <div className="no-print">
      {mounted && (
        <div ref={panel} role="dialog" aria-label={title} id="ask-ziira-panel" tabIndex={-1} hidden={!open}
          className={cx("fixed z-50 flex flex-col bg-surface shadow-pop animate-rise",
            "inset-0 sm:inset-auto sm:bottom-20 sm:right-5 sm:h-[560px] sm:max-h-[calc(100vh-6rem)] sm:w-[400px] sm:rounded-2xl sm:border sm:border-line",
            !open && "hidden")}>
          <div className="flex shrink-0 items-center justify-between border-b border-line px-4 py-3 pt-[max(0.75rem,env(safe-area-inset-top))] sm:pt-3">
            <h2 className="inline-flex flex-wrap items-center gap-2 text-base font-semibold">{title}<AiBadge short /></h2>
            <button type="button" aria-label={t("ai.closeAsk")} onClick={() => show(false)} className="rounded-lg p-1.5 text-muted hover:bg-sunken hover:text-ink"><X className="h-4 w-4" /></button>
          </div>
          <div className="min-h-0 flex-1"><AskBox autoAsk={auto} /></div>
        </div>
      )}
      <button ref={button} type="button" aria-label={title} aria-expanded={open} aria-controls="ask-ziira-panel" onClick={() => show(!open)}
        className={cx("fixed bottom-[max(1rem,env(safe-area-inset-bottom))] right-4 z-40 inline-flex h-12 items-center gap-2 rounded-full btn-gradient px-4 text-sm font-semibold shadow-pop sm:right-5",
          open && "max-sm:hidden")}>
        <Sparkles className="h-5 w-5" /><span className="hidden sm:inline">{title}</span>
      </button>
    </div>
  );
}
