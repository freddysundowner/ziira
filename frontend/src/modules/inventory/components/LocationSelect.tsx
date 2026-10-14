import { Select } from "@/sdk";

import { locationLabel, useLocations } from "../lookups";

/** A location dropdown. `kinds` limits the list (e.g. not "transit" for a count); `companyId` limits it to one company. */
export function LocationSelect({ value, onChange, companyId, kinds, allLabel, id, label, exclude }: {
  value: string; onChange: (id: string) => void; companyId?: string; kinds?: string[]; allLabel?: string; id?: string; label: string; exclude?: string;
}) {
  const locations = useLocations();
  const options = (locations.data ?? []).filter((l) => l.is_active && (!companyId || l.company_id === companyId) && (!kinds || kinds.includes(l.kind)) && l.id !== exclude);
  return (
    <Select id={id} aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} disabled={locations.isLoading}>
      {allLabel !== undefined ? <option value="">{allLabel}</option> : <option value="">{locations.error ? "—" : ""}</option>}
      {options.map((l) => <option key={l.id} value={l.id}>{locationLabel(l)}</option>)}
    </Select>
  );
}
