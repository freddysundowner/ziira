import { Plus, X } from "lucide-react";

import { Button, IconButton, Input, useTranslation } from "@/sdk";

import type { IdentifierRow } from "../lib";

/** Free name/value pairs that identify an item (plate, serial number, IMEI, size, address...). */
export function IdentifierRows({ rows, onChange, large }: { rows: IdentifierRow[]; onChange: (rows: IdentifierRow[]) => void; large?: boolean }) {
  const { t } = useTranslation("jobs");
  const set = (i: number, patch: Partial<IdentifierRow>) => onChange(rows.map((r, at) => (at === i ? { ...r, ...patch } : r)));
  const height = large ? "h-11" : undefined;
  return (
    <div className="space-y-2">
      {rows.map((row, i) => (
        <div key={i} className="flex items-center gap-2">
          <Input aria-label={t("identifiers.name")} placeholder={t("identifiers.namePlaceholder")} className={height} maxLength={40} value={row.name} onChange={(e) => set(i, { name: e.target.value })} list="jobs-identifier-names" />
          <Input aria-label={t("identifiers.value")} placeholder={t("identifiers.valuePlaceholder")} className={height} maxLength={120} value={row.value} onChange={(e) => set(i, { value: e.target.value })} />
          {rows.length > 1 && <IconButton label={t("identifiers.remove")} onClick={() => onChange(rows.filter((_, at) => at !== i))}><X className="h-4 w-4" /></IconButton>}
        </div>
      ))}
      <datalist id="jobs-identifier-names">{(["plate", "serial", "imei", "size", "address", "colour"] as const).map((n) => <option key={n} value={t(`identifiers.suggest.${n}`)} />)}</datalist>
      <Button variant="ghost" size="sm" onClick={() => onChange([...rows, { name: "", value: "" }])}><Plus className="h-4 w-4" />{t("identifiers.add")}</Button>
    </div>
  );
}
