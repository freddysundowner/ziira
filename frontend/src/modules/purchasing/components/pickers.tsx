import { Combobox, useTranslation } from "@/sdk";

import { searchProducts, searchSuppliers, useProduct, useSupplier } from "../hooks";

export function SupplierPicker({ value, onChange, id, invalid, disabled }: { value: string; onChange: (id: string) => void; id?: string; invalid?: boolean; disabled?: boolean }) {
  const { t } = useTranslation("purchasing");
  const current = useSupplier(value || null);
  return <Combobox id={id} value={value} onChange={(v) => onChange(v)} search={searchSuppliers} selectedLabel={current.data?.name} placeholder={t("pickSupplier")} invalid={invalid} disabled={disabled} />;
}

export function ProductPicker({ value, onChange, id, invalid }: { value: string; onChange: (id: string) => void; id?: string; invalid?: boolean }) {
  const { t } = useTranslation("purchasing");
  const current = useProduct(value || null);
  return <Combobox id={id} value={value} onChange={(v) => onChange(v)} search={searchProducts} selectedLabel={current.data ? `${current.data.name} (${current.data.sku})` : undefined} placeholder={t("pickProduct")} invalid={invalid} />;
}
