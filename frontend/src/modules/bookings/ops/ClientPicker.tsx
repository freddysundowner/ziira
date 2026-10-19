import { useCallback } from "react";

import { api, Combobox, unwrap } from "@/sdk";

/** Find a client by name or phone (two letters or more). The answer is the client's id. */
export function ClientPicker({ companyId, value, onChange, label, id, placeholder }: { companyId: string; value: string; onChange: (id: string, name?: string) => void; label?: string; id?: string; placeholder: string }) {
  const search = useCallback(async (text: string) => {
    if (!companyId || text.trim().length < 2) return [];
    const rows = await unwrap(api.GET("/api/v1/bookings/clients/search", { params: { query: { company_id: companyId, q: text.trim() } } }));
    return rows.map((r) => ({ value: r.id, label: r.name }));
  }, [companyId]);
  return <Combobox id={id} value={value} clearable search={search} selectedLabel={label} placeholder={placeholder} onChange={(v, o) => onChange(v, o?.label)} />;
}
