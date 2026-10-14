import { Plus, X } from "lucide-react";

import { Button, Combobox, IconButton, Input, NumberInput, type Option, Select, useTranslation } from "@/sdk";

export interface EditorLine {
  key: string;
  account_id: string;
  branch_id: string;
  description: string;
  debit: string;
  credit: string;
}

export const blankLine = (): EditorLine => ({ key: crypto.randomUUID(), account_id: "", branch_id: "", description: "", debit: "", credit: "" });

/** Editable journal lines. Typing a debit clears the credit on that line and the other way round, so a line never has both. */
export function JournalLinesEditor({ lines, onChange, accounts, branches }: {
  lines: EditorLine[]; onChange: (lines: EditorLine[]) => void; accounts: Option[]; branches: { id: string; name: string }[];
}) {
  const { t } = useTranslation("finance");
  const update = (key: string, patch: Partial<EditorLine>) => onChange(lines.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  return (
    <div className="space-y-3">
      <div className="hidden grid-cols-[minmax(0,2.2fr)_minmax(0,1.2fr)_minmax(0,1.2fr)_9rem_9rem_2.25rem] gap-2 px-1 text-xs font-medium uppercase tracking-wide text-muted lg:grid">
        <span>{t("account")}</span><span>{t("branch")}</span><span>{t("description")}</span><span className="text-right">{t("debit")}</span><span className="text-right">{t("credit")}</span><span />
      </div>
      {lines.map((l, i) => (
        <div key={l.key} className="grid gap-2 rounded-xl border border-line p-3 lg:grid-cols-[minmax(0,2.2fr)_minmax(0,1.2fr)_minmax(0,1.2fr)_9rem_9rem_2.25rem] lg:items-start lg:border-0 lg:p-0">
          <Combobox value={l.account_id} onChange={(v) => update(l.key, { account_id: v })} options={accounts} placeholder={`${t("account")} ${i + 1}`} />
          {branches.length > 0 ? (
            <Select aria-label={t("branch")} value={l.branch_id} onChange={(e) => update(l.key, { branch_id: e.target.value })}>
              <option value="">{t("noBranch")}</option>
              {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </Select>
          ) : <span />}
          <Input aria-label={t("description")} placeholder={t("description")} maxLength={500} value={l.description} onChange={(e) => update(l.key, { description: e.target.value })} />
          <NumberInput aria-label={t("debit")} placeholder={t("debit")} value={l.debit} onChange={(v) => update(l.key, { debit: v, credit: v ? "" : l.credit })} />
          <NumberInput aria-label={t("credit")} placeholder={t("credit")} value={l.credit} onChange={(v) => update(l.key, { credit: v, debit: v ? "" : l.debit })} />
          <IconButton label={t("removeLine")} disabled={lines.length <= 2} onClick={() => onChange(lines.filter((x) => x.key !== l.key))}><X className="h-4 w-4" /></IconButton>
        </div>
      ))}
      <Button variant="secondary" size="sm" onClick={() => onChange([...lines, blankLine()])}><Plus className="h-4 w-4" />{t("addLine")}</Button>
    </div>
  );
}
