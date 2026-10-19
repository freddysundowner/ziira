import type { ReactNode } from "react";

import { cx } from "./cx";

/**
 * Several labelled figures in a row (a Home widget's "Open / Ready / Late"). Always use these two for that, never hand-made columns:
 * the figures sit side by side in compact columns, wrapping to fewer columns (one at under ~200px), a label wraps inside its own column instead of running
 * into the next one, and every figure (a small sentence-case label, the number just under it) sits on the bottom line of its row whatever the label's length (English or Swahili).
 */
export function StatRow({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("grid min-w-0 grid-cols-[repeat(auto-fit,minmax(min(100%,4.25rem),1fr))] gap-x-3 gap-y-2", className)}>{children}</div>;
}

/** One figure with its label above it. The number shrinks with the screen and wraps rather than leaving its box. */
export function Figure({ label, value, tone, hint }: { label: ReactNode; value: ReactNode; tone?: "ok" | "bad" | "warn"; hint?: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col justify-between gap-0.5">
      <p className="text-xs leading-tight text-muted [overflow-wrap:anywhere]">{label}</p>
      <div className="min-w-0">
        <p className={cx("tnum text-[length:clamp(1.125rem,5.5vw,1.5rem)] font-semibold leading-tight [overflow-wrap:anywhere] sm:text-2xl", tone === "ok" && "text-ok", tone === "bad" && "text-bad", tone === "warn" && "text-warn")}>{value}</p>
        {hint && <p className="mt-0.5 text-xs text-muted [overflow-wrap:anywhere]">{hint}</p>}
      </div>
    </div>
  );
}
