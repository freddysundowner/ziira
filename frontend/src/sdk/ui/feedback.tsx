import { AlertTriangle, Inbox, Loader2, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";

import { cx } from "./cx";

export type BadgeTone = "neutral" | "ok" | "warn" | "bad" | "info" | "brand";

const TONES: Record<BadgeTone, string> = {
  neutral: "bg-sunken text-muted",
  ok: "bg-ok-soft text-ok",
  warn: "bg-warn-soft text-warn",
  bad: "bg-bad-soft text-bad",
  info: "bg-info-soft text-info",
  brand: "bg-brand-soft text-brand-strong",
};

export function Badge({ tone = "neutral", children, className }: { tone?: BadgeTone; children: ReactNode; className?: string }) {
  return <span className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium", TONES[tone], className)}>{children}</span>;
}

/** Statuses the backend sends as codes, mapped to a colour. Unknown codes stay neutral. */
const STATUS_TONE: Record<string, BadgeTone> = {
  active: "ok", posted: "ok", paid: "ok", approved: "ok", completed: "ok", received: "ok", verified: "ok", open: "info", closed: "neutral",
  draft: "neutral", pending: "warn", submitted: "warn", partial: "warn", partially_paid: "warn", unpaid: "warn", overdue: "bad",
  rejected: "bad", voided: "bad", cancelled: "bad", failed: "bad", disabled: "neutral", inactive: "neutral", reversed: "bad",
};
export function StatusBadge({ status }: { status: string | null | undefined }) {
  const s = (status ?? "").toLowerCase();
  const label = s ? s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()) : "—";
  return <Badge tone={STATUS_TONE[s] ?? "neutral"}>{label}</Badge>;
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 aria-label="Loading" className={cx("h-4 w-4 animate-spin", className)} />;
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cx("animate-pulse2 rounded-md bg-sunken", className)} />;
}

export function SkeletonRows({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div className="space-y-3 p-4" role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, r) => (
        <div key={r} className="flex gap-4">
          {Array.from({ length: cols }, (_, c) => <Skeleton key={c} className={cx("h-4", c === 0 ? "w-1/4" : "flex-1")} />)}
        </div>
      ))}
    </div>
  );
}

export function EmptyState({ title, hint, action, icon }: { title: string; hint?: string; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      <div className="mb-3 rounded-full bg-sunken p-3 text-muted">{icon ?? <Inbox className="h-6 w-6" />}</div>
      <p className="font-medium">{title}</p>
      {hint && <p className="mt-1 max-w-sm text-sm text-muted">{hint}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({ message, onRetry, title = "Something went wrong" }: { message?: string; onRetry?: () => void; title?: string }) {
  return (
    <div role="alert" className="flex flex-col items-center px-6 py-12 text-center">
      <div className="mb-3 rounded-full bg-bad-soft p-3 text-bad"><AlertTriangle className="h-6 w-6" /></div>
      <p className="font-medium">{title}</p>
      {message && <p className="mt-1 max-w-md text-sm text-muted">{message}</p>}
      {onRetry && (
        <button onClick={onRetry} className="mt-4 inline-flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium hover:bg-sunken">
          <RefreshCw className="h-4 w-4" /> Try again
        </button>
      )}
    </div>
  );
}

export function Alert({ tone = "info", children, className }: { tone?: "info" | "ok" | "warn" | "bad"; children: ReactNode; className?: string }) {
  const t = { info: "bg-info-soft text-info", ok: "bg-ok-soft text-ok", warn: "bg-warn-soft text-warn", bad: "bg-bad-soft text-bad" }[tone];
  return <div role={tone === "bad" ? "alert" : "status"} className={cx("rounded-lg px-3 py-2 text-sm", t, className)}>{children}</div>;
}

/** Shows an error text under a form, when there is one. */
export function ErrorText({ children }: { children?: ReactNode }) {
  return children ? <p role="alert" className="text-sm text-bad">{children}</p> : null;
}
