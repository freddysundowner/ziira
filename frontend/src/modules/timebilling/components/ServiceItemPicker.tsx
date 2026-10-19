import { useCallback } from "react";

import { api, Combobox, unwrap, useQuery, useTranslation } from "@/sdk";

/** Pick a service item (a product of type "service") that time or expenses are invoiced under. */
export function ServiceItemPicker({ value, onChange, id, clearable = true, invalid }: { value: string; onChange: (id: string) => void; id?: string; clearable?: boolean; invalid?: boolean }) {
  const { t } = useTranslation("timebilling");
  const current = useQuery({
    queryKey: ["timebilling", "service-item", value], enabled: !!value, staleTime: 5 * 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/products/products/{product_id}", { params: { path: { product_id: value } } })),
  });
  const search = useCallback(async (text: string) => {
    const rows = await unwrap(api.GET("/api/v1/products/products", { params: { query: { search: text.trim() || undefined, product_type: "service", limit: 100 } } }));
    return rows.filter((p) => p.is_active).map((p) => ({ value: p.id, label: p.name, hint: p.sku }));
  }, []);
  return <Combobox id={id} value={value} selectedLabel={current.data?.name} search={search} placeholder={t("pickService")} clearable={clearable} invalid={invalid} onChange={(v) => onChange(v)} />;
}
