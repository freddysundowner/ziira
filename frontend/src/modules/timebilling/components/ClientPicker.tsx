import { useCallback } from "react";

import { api, Combobox, unwrap, useTranslation } from "@/sdk";

/** Look a customer (a client of the business) up by name as the person types. */
export function ClientPicker({ value, label, onChange, invalid, id, disabled, clearable }: {
  value: string; label?: string; onChange: (id: string, name: string) => void; invalid?: boolean; id?: string; disabled?: boolean; clearable?: boolean;
}) {
  const { t } = useTranslation("timebilling");
  const search = useCallback(async (text: string) => {
    const rows = await unwrap(api.GET("/api/v1/crm/customers", { params: { query: { search: text.trim() || undefined, limit: 30 } } }));
    return rows.map((c) => ({ value: c.id, label: c.name, hint: c.phone ?? c.email ?? undefined }));
  }, []);
  return <Combobox id={id} value={value} selectedLabel={label} search={search} placeholder={t("pickClient")} invalid={invalid} disabled={disabled} clearable={clearable} onChange={(v, o) => onChange(v, o?.label ?? "")} />;
}
