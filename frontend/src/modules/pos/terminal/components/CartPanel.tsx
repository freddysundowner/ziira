import { Minus, Pause, Pencil, Plus, Trash2 } from "lucide-react";

import { Badge, Button, cx, EmptyState, IconButton, money, quantity, useTranslation } from "@/sdk";

import { type CartLine, cartDiscount, cartProblem, cartTotal, itemCount, lineProblem, lineTotal, num, text } from "../cart";
import type { ReactNode } from "react";

/** The sale being rung up: lines with quantity buttons, the total, and the big Pay button. */
export function CartPanel({ lines, currency, customer, heldCount, onStep, onEdit, onRemove, onHold, onClear, onShowHeld, onPay }: {
  lines: CartLine[]; currency: string; customer: ReactNode; heldCount: number; onStep: (key: string, delta: number) => void; onEdit: (key: string) => void;
  onRemove: (key: string) => void; onHold: () => void; onClear: () => void; onShowHeld: () => void; onPay: () => void;
}) {
  const { t } = useTranslation("pos");
  const total = cartTotal(lines);
  const discount = cartDiscount(lines);
  const blocked = cartProblem(lines);

  return (
    <section className="flex min-h-0 flex-1 flex-col bg-surface" aria-label={t("terminal.cart.title")}>
      <div className="shrink-0 space-y-2 border-b border-line p-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">{t("terminal.cart.title")}</h2>
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="sm" onClick={onShowHeld}>{t("terminal.hold.list")}{heldCount > 0 && <Badge tone="brand">{heldCount}</Badge>}</Button>
            <Button variant="ghost" size="sm" onClick={onHold} disabled={lines.length === 0} title={t("terminal.hold.shortcut")}><Pause className="h-3.5 w-3.5" />{t("terminal.hold.action")}</Button>
            <Button variant="ghost" size="sm" onClick={onClear} disabled={lines.length === 0}><Trash2 className="h-3.5 w-3.5" />{t("terminal.cart.clear")}</Button>
          </div>
        </div>
        {customer}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {lines.length === 0 ? (
          <EmptyState title={t("terminal.cart.empty")} hint={t("terminal.cart.emptyHint")} />
        ) : (
          <ul className="divide-y divide-line">
            {lines.map((l) => {
              const problem = lineProblem(l);
              const short = l.stock !== "" && num(l.quantity) > num(l.stock);
              return (
                <li key={l.key} className="px-3 py-2.5">
                  <div className="flex items-start gap-2">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{l.name}</p>
                      <p className="tnum text-xs text-muted">
                        {money(l.price || "0", currency)} × {quantity(l.quantity)}
                        {num(l.discount) > 0 && <span className="ml-1.5 text-ok">− {money(l.discount, currency)}</span>}
                      </p>
                    </div>
                    <p className="tnum shrink-0 text-sm font-semibold">{money(text(lineTotal(l)), currency)}</p>
                  </div>
                  <div className="mt-1.5 flex items-center gap-1">
                    <IconButton label={t("terminal.cart.less")} className="h-10 w-10 border border-line" onClick={() => onStep(l.key, -1)}><Minus className="h-4 w-4" /></IconButton>
                    <button type="button" onClick={() => onEdit(l.key)} aria-label={t("terminal.cart.edit")} className="tnum h-10 min-w-[3.5rem] rounded-lg px-2 text-center text-sm font-semibold hover:bg-sunken">{quantity(l.quantity)}</button>
                    <IconButton label={t("terminal.cart.more")} className="h-10 w-10 border border-line" onClick={() => onStep(l.key, 1)}><Plus className="h-4 w-4" /></IconButton>
                    <IconButton label={t("terminal.cart.edit")} className="h-10 w-10" onClick={() => onEdit(l.key)}><Pencil className="h-4 w-4" /></IconButton>
                    <div className="flex-1" />
                    {short && <Badge tone="warn">{t("terminal.cart.lowStock")}</Badge>}
                    <IconButton label={t("terminal.cart.remove")} className="h-10 w-10 hover:text-bad" onClick={() => onRemove(l.key)}><Trash2 className="h-4 w-4" /></IconButton>
                  </div>
                  {problem && <p role="alert" className="mt-1 text-xs text-bad">{t(`terminal.line.problem.${problem}`)}</p>}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="shrink-0 space-y-2 border-t border-line bg-surface p-3">
        <dl className="space-y-0.5 text-sm">
          <div className="flex justify-between text-muted"><dt>{t("terminal.cart.items")}</dt><dd className="tnum">{quantity(itemCount(lines))}</dd></div>
          {discount > 0 && <div className="flex justify-between text-muted"><dt>{t("terminal.cart.discounts")}</dt><dd className="tnum">− {money(text(discount), currency)}</dd></div>}
          <div className="flex items-baseline justify-between pt-1"><dt className="text-base font-semibold">{t("terminal.cart.total")}</dt><dd className="tnum text-2xl font-bold">{money(text(total), currency)}</dd></div>
          <p className="text-right text-[11px] text-muted">{t("terminal.cart.taxIncluded")}</p>
        </dl>
        <Button size="lg" className={cx("h-14 w-full text-lg")} disabled={lines.length === 0 || blocked !== null} onClick={onPay}>
          {t("terminal.cart.pay")} {lines.length > 0 && money(text(total), currency)}
          <kbd className="ml-2 hidden rounded border border-white/30 px-1.5 text-[11px] font-normal sm:inline">F8</kbd>
        </Button>
      </div>
    </section>
  );
}
