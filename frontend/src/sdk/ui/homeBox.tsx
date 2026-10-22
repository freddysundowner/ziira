import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { useTranslation } from "../i18n";
import { cx } from "./cx";
import { Skeleton } from "./feedback";

export interface HomeRow {
  key: string;
  /** The main text (a name, a time and a service ...). Long text is cut with an ellipsis. */
  left: ReactNode;
  /** A short value at the right (a status, a date, a count). */
  right?: ReactNode;
}

export interface HomeBoxProps {
  /** `"stat"`: a compact number tile; anything else: the full box. Pass the widget's `variant` prop straight through. */
  variant?: unknown;
  /** Where the box leads: the screen that lists what the number counts. */
  to: string;
  /** The number (already formatted); money is passed formatted too. */
  value: ReactNode;
  /** One short context line under the number. */
  hint?: ReactNode;
  hintTone?: "warn" | "bad";
  tone?: "ok" | "bad" | "warn";
  loading?: boolean;
  error?: string;
  onRetry?: () => void;
  /** Set when there is nothing to show: the tile keeps its 0 and this line, the full box shrinks to the one-line "all clear" row. */
  clear?: string;
  /** A few rows under the number (full box only). */
  rows?: readonly HomeRow[];
  /** Text of the link to the screen (full box only). */
  openLabel?: string;
}

/**
 * The shared body of a Home box that counts something ("Free now", "Claims waiting"). Every state is designed here once so the
 * boxes of different modules behave alike: loading (skeleton), error (message and retry), nothing to show (tile: 0 and a line;
 * box: the one-line "all clear" row), and the figure, long values wrapping instead of overflowing at 320 px.
 * Text comes in already translated; the module that owns the data decides what is counted.
 */
export function HomeBox({ variant, to, value, hint, hintTone, tone, loading, error, onRetry, clear, rows = [], openLabel }: HomeBoxProps) {
  const { t } = useTranslation();
  const tile = variant === "stat";
  if (error) {
    return (
      <div role="alert" className="min-w-0 text-sm text-bad">
        <p className="[overflow-wrap:anywhere]">{error}</p>
        {onRetry && <button type="button" onClick={onRetry} className="mt-1 text-xs font-medium underline">{t("home.retry")}</button>}
      </div>
    );
  }
  if (loading) return <Skeleton className={tile ? "h-10 w-full" : "h-16 w-full"} />;
  if (tile) {
    return (
      <Link to={to} className="block min-w-0">
        <p className={cx("tnum text-2xl font-semibold leading-tight [overflow-wrap:anywhere]", tone === "bad" && "text-bad", tone === "warn" && "text-warn", tone === "ok" && "text-ok")}>{value}</p>
        {(clear || hint) && <p className={cx("mt-1 line-clamp-2 text-xs [overflow-wrap:anywhere]", !clear && hintTone === "warn" ? "font-medium text-warn" : !clear && hintTone === "bad" ? "font-medium text-bad" : "text-muted")}>{clear ?? hint}</p>}
      </Link>
    );
  }
  if (clear) return <p data-clear className="text-sm text-muted">{clear}</p>;
  return (
    <div className="min-w-0 space-y-2">
      <Link to={to} className="block min-w-0">
        <p className={cx("tnum text-[length:clamp(1.25rem,6vw,1.75rem)] font-semibold leading-tight [overflow-wrap:anywhere] sm:text-3xl", tone === "bad" && "text-bad", tone === "warn" && "text-warn", tone === "ok" && "text-ok")}>{value}</p>
        {hint && <p className={cx("mt-0.5 text-xs [overflow-wrap:anywhere]", hintTone === "warn" ? "font-medium text-warn" : hintTone === "bad" ? "font-medium text-bad" : "text-muted")}>{hint}</p>}
      </Link>
      {rows.length > 0 && (
        <ul className="divide-y divide-line text-sm">
          {rows.map((r) => (
            <li key={r.key} className="flex items-center justify-between gap-3 py-1.5">
              <span className="min-w-0 truncate">{r.left}</span>
              {r.right != null && <span className="shrink-0 text-xs text-muted">{r.right}</span>}
            </li>
          ))}
        </ul>
      )}
      {openLabel && <Link to={to} className="inline-block text-xs font-medium text-brand-strong hover:underline">{openLabel}</Link>}
    </div>
  );
}
