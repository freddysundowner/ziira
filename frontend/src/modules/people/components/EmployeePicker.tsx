import { useMemo } from "react";

import { Combobox } from "@/sdk";

import { searchEmployees } from "../lib/lookups";

/** Pick one employee, looked up on the server as the person types. */
export function EmployeePicker({ companyId, value, onChange, selectedLabel, placeholder, activeOnly, id, invalid }: {
  companyId: string; value: string; onChange: (id: string) => void; selectedLabel?: string; placeholder?: string; activeOnly?: boolean; id?: string; invalid?: boolean;
}) {
  // The lookup must keep its identity between renders, or the combobox would ask the server again on every render.
  const search = useMemo(() => searchEmployees(companyId, activeOnly ? "active" : undefined), [companyId, activeOnly]);
  return <Combobox id={id} invalid={invalid} value={value} onChange={(v) => onChange(v)} selectedLabel={selectedLabel} placeholder={placeholder} search={search} />;
}
