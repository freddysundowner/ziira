import { Plus, X } from "lucide-react";

import { api, Button, IconButton, Input, unwrap, useQuery, useTranslation } from "@/sdk";

import type { IdentifierRow } from "../lib";

/** Free name/value pairs that identify an item (plate, serial number, IMEI, size, address...). */
const isVinRow = (row: IdentifierRow): boolean => /^vin$/i.test(row.name.trim()) && row.value.replace(/\s/g, "").length === 17;

/** What a 17-character VIN says by itself: the make, the year and whether the check digit adds up. */
function VinHint({ value }: { value: string }) {
  const { t } = useTranslation("jobs");
  const clean = value.replace(/\s/g, "").toUpperCase();
  const read = useQuery({ queryKey: ["jobs", "vin", clean], staleTime: 3_600_000, retry: false, queryFn: () => unwrap(api.GET("/api/v1/jobs/vin/{vin}", { params: { path: { vin: clean } } })) });
  if (!read.data) return null;
  const v = read.data;
  if (v.problem) return <p className="text-xs text-bad">{v.problem}</p>;
  const what = [v.make, v.year].filter(Boolean).join(", ");
  return (
    <p className="text-xs text-muted">
      {what ? t("floor.vin.reads", { what }) : t("floor.vin.unknownMake")}
      {v.check_digit_ok === false && <span className="ml-1 text-warn">{t("floor.vin.checkFailed")}</span>}
    </p>
  );
}

export function IdentifierRows({ rows, onChange, large }: { rows: IdentifierRow[]; onChange: (rows: IdentifierRow[]) => void; large?: boolean }) {
  const { t } = useTranslation("jobs");
  const set = (i: number, patch: Partial<IdentifierRow>) => onChange(rows.map((r, at) => (at === i ? { ...r, ...patch } : r)));
  const height = large ? "h-11" : undefined;
  return (
    <div className="space-y-2">
      {rows.map((row, i) => (
        <div key={i} className="space-y-1">
        <div className="flex items-center gap-2">
          <Input aria-label={t("identifiers.name")} placeholder={t("identifiers.namePlaceholder")} className={height} maxLength={40} value={row.name} onChange={(e) => set(i, { name: e.target.value })} list="jobs-identifier-names" />
          <Input aria-label={t("identifiers.value")} placeholder={t("identifiers.valuePlaceholder")} className={height} maxLength={120} value={row.value} onChange={(e) => set(i, { value: e.target.value })} />
          {rows.length > 1 && <IconButton label={t("identifiers.remove")} onClick={() => onChange(rows.filter((_, at) => at !== i))}><X className="h-4 w-4" /></IconButton>}
        </div>
          {isVinRow(row) && <VinHint value={row.value} />}
        </div>
      ))}
      <datalist id="jobs-identifier-names">{(["plate", "vin", "serial", "imei", "size", "address", "colour"] as const).map((n) => <option key={n} value={t(`identifiers.suggest.${n}`)} />)}</datalist>
      <Button variant="ghost" size="sm" onClick={() => onChange([...rows, { name: "", value: "" }])}><Plus className="h-4 w-4" />{t("identifiers.add")}</Button>
    </div>
  );
}
