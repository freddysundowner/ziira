import { useState } from "react";

import { Checkbox, ErrorState, Input, Skeleton, useTranslation } from "@/sdk";

import { usePlatformUnits } from "../../catalog";

/** A searchable checklist of the platform's units (the kernel is always on, so it is not listed). */
export function UnitPicker({ label, hint, selected, onChange }: { label: string; hint?: string; selected: string[]; onChange: (units: string[]) => void }) {
  const { t } = useTranslation("operator");
  const units = usePlatformUnits();
  const [search, setSearch] = useState("");
  const q = search.trim().toLowerCase();
  const all = (units.data ?? []).filter((u) => u.kind !== "kernel");
  // Units already chosen but no longer found on this server stay listed, so saving never drops them silently.
  const known = new Set(all.map((u) => u.name));
  const missing = selected.filter((n) => !known.has(n));
  const shown = all.filter((u) => !q || `${u.title} ${u.name}`.toLowerCase().includes(q));
  const toggle = (name: string) => onChange(selected.includes(name) ? selected.filter((n) => n !== name) : [...selected, name]);
  const labelId = `unit-picker-${label.replace(/\W+/g, "-")}`;

  return (
    <div>
      <p id={labelId} className="text-sm font-medium">{label}</p>
      {hint && <p className="text-xs text-muted">{hint}</p>}
      {units.isPending && <Skeleton className="mt-2 h-20 w-full" />}
      {units.isError && <ErrorState title={t("plans.editor.unitsFailed")} message={units.error.message} onRetry={() => void units.refetch()} />}
      {units.data && (
        <div className="mt-2 rounded-lg border border-line">
          <div className="border-b border-line p-2"><Input aria-label={t("plans.editor.searchUnits")} placeholder={t("plans.editor.searchUnits")} value={search} onChange={(e) => setSearch(e.target.value)} /></div>
          <ul aria-labelledby={labelId} className="grid max-h-48 gap-x-4 gap-y-1 overflow-y-auto p-2 sm:grid-cols-2">
            {shown.map((u) => (
              <li key={u.name}><Checkbox checked={selected.includes(u.name)} onChange={() => toggle(u.name)} label={<span>{u.title} <span className="font-mono text-xs text-muted">{u.name}</span>{u.status === "available" && <span className="ml-1 text-xs text-warn">{t("plans.editor.notInstalled")}</span>}</span>} /></li>
            ))}
            {missing.map((n) => <li key={n}><Checkbox checked onChange={() => toggle(n)} label={<span className="font-mono text-xs">{n} <span className="text-warn">{t("plans.editor.notFound")}</span></span>} /></li>)}
            {shown.length === 0 && missing.length === 0 && <li className="text-sm text-muted">{t("plans.editor.noUnitMatch")}</li>}
          </ul>
        </div>
      )}
      {selected.length > 0 && <p className="mt-1 text-xs text-muted">{t("plans.editor.selectedCount", { count: selected.length })}</p>}
    </div>
  );
}
