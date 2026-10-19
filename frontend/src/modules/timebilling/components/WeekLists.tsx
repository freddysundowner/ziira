import { Pencil, Trash2 } from "lucide-react";

import { Badge, formatDate, IconButton, money, useTranslation } from "@/sdk";

import { formatDuration } from "../lib";
import type { Entry, Expense } from "../types";

/** The entries of a week that are not grid cells (timer and quick log), each with its note: edit or delete while the week is open. */
export function EntryList({ entries, canEdit, onEdit, onDelete, showPerson }: { entries: readonly Entry[]; canEdit: boolean; onEdit?: (e: Entry) => void; onDelete?: (e: Entry) => void; showPerson?: boolean }) {
  const { t } = useTranslation("timebilling");
  if (entries.length === 0) return <p className="px-4 py-6 text-center text-sm text-muted">{t("entries.none")}</p>;
  return (
    <ul className="divide-y divide-line">
      {entries.map((e) => (
        <li key={e.id} className="flex items-center gap-3 px-4 py-2.5 text-sm">
          <span className="w-20 shrink-0 text-xs text-muted">{formatDate(e.work_date)}</span>
          <span className="min-w-0 flex-1">
            <span className="block truncate font-medium">{e.project_code} · {e.project_name}{e.task ? ` · ${e.task}` : ""}</span>
            {(e.note || showPerson) && <span className="block truncate text-xs text-muted">{showPerson && e.user_name}{showPerson && e.note ? " · " : ""}{e.note}</span>}
          </span>
          {!e.billable && <Badge>{t("notBillable")}</Badge>}
          <span className="tnum w-16 shrink-0 text-right font-medium">{formatDuration(e.minutes)}</span>
          {canEdit && (
            <span className="flex shrink-0">
              <IconButton label={t("edit")} onClick={() => onEdit?.(e)}><Pencil className="h-4 w-4" /></IconButton>
              <IconButton label={t("delete")} onClick={() => onDelete?.(e)}><Trash2 className="h-4 w-4" /></IconButton>
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

/** The expenses of a week with their markup. */
export function ExpenseList({ expenses, currency, canEdit, onEdit, onDelete }: { expenses: readonly Expense[]; currency?: string; canEdit: boolean; onEdit?: (e: Expense) => void; onDelete?: (e: Expense) => void }) {
  const { t } = useTranslation("timebilling");
  if (expenses.length === 0) return <p className="px-4 py-6 text-center text-sm text-muted">{t("expenses.none")}</p>;
  return (
    <ul className="divide-y divide-line">
      {expenses.map((x) => (
        <li key={x.id} className="flex items-center gap-3 px-4 py-2.5 text-sm">
          <span className="w-20 shrink-0 text-xs text-muted">{formatDate(x.expense_date)}</span>
          <span className="min-w-0 flex-1">
            <span className="block truncate font-medium">{x.description}</span>
            <span className="block truncate text-xs text-muted">{x.project_code} · {x.project_name}{x.category ? ` · ${x.category}` : ""}{x.reference ? ` · ${x.reference}` : ""}</span>
          </span>
          {Number(x.markup_percent) > 0 && <Badge tone="info">{t("expenses.markupShort", { percent: Number(x.markup_percent) })}</Badge>}
          {!x.billable && <Badge>{t("notBillable")}</Badge>}
          <span className="tnum w-24 shrink-0 text-right font-medium">{money(x.amount, currency)}</span>
          {canEdit && (
            <span className="flex shrink-0">
              <IconButton label={t("edit")} onClick={() => onEdit?.(x)}><Pencil className="h-4 w-4" /></IconButton>
              <IconButton label={t("delete")} onClick={() => onDelete?.(x)}><Trash2 className="h-4 w-4" /></IconButton>
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}
