import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";

import { cx, money, percent, quantity, useTranslation } from "@/sdk";

import { changeOf, type Figure } from "../logic";

/** A figure's value in its own kind: money in the company's currency, a count, or a percent. */
export function formatFigure(f: Pick<Figure, "kind">, value: string | null, currency: string): string {
  if (value === null) return "—";
  if (f.kind === "money") return money(value, currency);
  if (f.kind === "percent") return percent(value);
  return quantity(value, 0);
}

const TONE = { ok: "text-ok", bad: "text-bad", neutral: "text-muted" } as const;

/** One figure for today, with how it moved against yesterday (green good, red bad). */
export default function FigureCard({ figure, currency }: { figure: Figure; currency: string }) {
  const { t } = useTranslation("command");
  const c = changeOf(figure.value, figure.previous, figure.higher_is_better);
  const Icon = c.direction === "up" ? ArrowUpRight : c.direction === "down" ? ArrowDownRight : Minus;
  const pct = c.percent === null ? null : `${c.percent > 0 ? "+" : ""}${Math.round(c.percent * 10) / 10}%`;
  return (
    <div className="rounded-xl border border-line bg-surface p-4 shadow-card">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{figure.label}</p>
      <p className="tnum mt-1 text-2xl font-semibold">{formatFigure(figure, figure.value, currency)}</p>
      <p className={cx("mt-1 flex flex-wrap items-center gap-x-1.5 text-xs", TONE[c.tone])}>
        {c.direction === "none" ? t("noYesterday") : (
          <>
            <Icon className="h-3.5 w-3.5" aria-hidden />
            <span className="font-medium">{c.direction === "flat" ? t("unchanged") : pct ?? t("newToday")}</span>
            <span className="text-muted">{t("yesterdayWas", { value: formatFigure(figure, figure.previous, currency) })}</span>
          </>
        )}
      </p>
    </div>
  );
}
