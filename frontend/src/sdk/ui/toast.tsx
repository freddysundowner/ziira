import { CheckCircle2, Info, TriangleAlert, X, XCircle } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useState } from "react";

import { onToast, type ToastMessage, type Tone } from "../notify";
import { cx } from "./cx";

const STYLE: Record<Tone, { box: string; icon: ReactNode }> = {
  ok: { box: "border-ok/30", icon: <CheckCircle2 className="h-4 w-4 text-ok" /> },
  bad: { box: "border-bad/40", icon: <XCircle className="h-4 w-4 text-bad" /> },
  info: { box: "border-line", icon: <Info className="h-4 w-4 text-info" /> },
  warn: { box: "border-warn/40", icon: <TriangleAlert className="h-4 w-4 text-warn" /> },
};

/** Shows toasts raised anywhere with `toast(...)`. Mount once, near the root. */
export function Toaster() {
  const [items, setItems] = useState<ToastMessage[]>([]);
  const dismiss = useCallback((id: number) => setItems((all) => all.filter((t) => t.id !== id)), []);
  useEffect(() => {
    onToast((t) => {
      setItems((all) => (all.some((x) => x.text === t.text && x.tone === t.tone) ? all : [...all.slice(-3), t]));
      window.setTimeout(() => dismiss(t.id), t.tone === "bad" ? 8000 : 4500);
    });
    return () => onToast(null);
  }, [dismiss]);
  return (
    <div className="no-print pointer-events-none fixed inset-x-0 bottom-0 z-[60] flex flex-col items-center gap-2 p-4 sm:items-end" aria-live="polite">
      {items.map((t) => (
        <div key={t.id} className={cx("pointer-events-auto flex w-full max-w-sm items-start gap-2.5 rounded-xl border bg-surface p-3 shadow-pop animate-rise", STYLE[t.tone].box)}>
          <span className="mt-0.5 shrink-0">{STYLE[t.tone].icon}</span>
          <p className="min-w-0 flex-1 text-sm [overflow-wrap:anywhere]">{t.text}</p>
          <button aria-label="Dismiss" onClick={() => dismiss(t.id)} className="text-muted hover:text-ink"><X className="h-4 w-4" /></button>
        </div>
      ))}
    </div>
  );
}
