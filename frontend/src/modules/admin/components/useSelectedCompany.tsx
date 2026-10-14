import { type ReactNode, useState } from "react";

import { Field, Select, useCompany } from "@/sdk";

/** The company a settings screen works on: the first one, with a picker only when the user has several. */
export function useSelectedCompany(label: string): { companyId: string | undefined; picker: ReactNode } {
  const { company, companies } = useCompany();
  const [chosen, setChosen] = useState<string>();
  const companyId = chosen ?? company?.id;
  const picker = companies.length > 1 ? (
    <Field label={label} className="max-w-xs">
      <Select value={companyId ?? ""} onChange={(e) => setChosen(e.target.value)}>
        {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
      </Select>
    </Field>
  ) : null;
  return { companyId, picker };
}
