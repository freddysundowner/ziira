import { Trash2 } from "lucide-react";
import type { ReactNode } from "react";

import { Card, cx, IconButton, money, quantity, useTranslation } from "@/sdk";

export interface Line {
  id: string;
  description: string;
  detail?: string;
  quantity: string;
  unit: string;
  total: string;
  cost?: string | null;
  voided: boolean;
  /** Small marks beside the description (part class, ordered, from the customer ...). */
  badges?: ReactNode;
  /** Buttons for this line (arrived, return, booked hours). */
  actions?: ReactNode;
}

/** Parts or labour lines of a job: removed lines stay visible, struck through. Costs show only when the server sent them. */
export function LinesTable({ title, lines, currency, qtyLabel, unitLabel, onRemove, canRemove, action, empty, showCost }: {
  title: string; lines: readonly Line[]; currency: string | undefined; qtyLabel: string; unitLabel: string;
  onRemove: (id: string) => void; canRemove: boolean; action?: ReactNode; empty: string; showCost: boolean;
}) {
  const { t } = useTranslation("jobs");
  return (
    <Card title={title} actions={action} flush>
      {lines.length === 0 ? <p className="px-4 py-6 text-center text-sm text-muted">{empty}</p> : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-line bg-sunken/60 text-xs uppercase tracking-wide text-muted">
              <tr>
                <th scope="col" className="px-4 py-2 font-medium">{t("lines.description")}</th>
                <th scope="col" className="px-2 py-2 text-right font-medium">{qtyLabel}</th>
                <th scope="col" className="hidden px-2 py-2 text-right font-medium sm:table-cell">{unitLabel}</th>
                {showCost && <th scope="col" className="hidden px-2 py-2 text-right font-medium md:table-cell">{t("lines.cost")}</th>}
                <th scope="col" className="px-4 py-2 text-right font-medium">{t("lines.total")}</th>
                <th scope="col" className="w-10"><span className="sr-only">{t("common.remove")}</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {lines.map((l) => (
                <tr key={l.id} className={cx(l.voided && "text-muted line-through")}>
                  <td className="px-4 py-2.5"><span className="block">{l.description}{l.badges && <span className="ml-2 inline-flex flex-wrap gap-1 align-middle no-underline">{l.badges}</span>}</span>{l.detail && <span className="block text-xs text-muted no-underline">{l.detail}</span>}{l.actions && !l.voided && <span className="mt-1 flex flex-wrap gap-1 no-underline">{l.actions}</span>}</td>
                  <td className="tnum px-2 py-2.5 text-right">{quantity(l.quantity)}</td>
                  <td className="tnum hidden px-2 py-2.5 text-right sm:table-cell">{money(l.unit, currency)}</td>
                  {showCost && <td className="tnum hidden px-2 py-2.5 text-right md:table-cell">{l.cost == null ? "—" : money(l.cost, currency)}</td>}
                  <td className="tnum px-4 py-2.5 text-right">{money(l.total, currency)}</td>
                  <td className="pr-2">{canRemove && !l.voided && <IconButton label={t("common.remove")} onClick={() => onRemove(l.id)}><Trash2 className="h-4 w-4" /></IconButton>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
