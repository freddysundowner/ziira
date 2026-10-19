import { Combobox, Select, useTranslation } from "@/sdk";

import { searchAssets, searchCustomers, searchProducts, searchServiceItems, useAsset, useCustomer, usePeople, useProduct } from "../hooks";

interface PickerProps {
  value: string;
  onChange: (id: string) => void;
  id?: string;
  invalid?: boolean;
  disabled?: boolean;
}

export function CustomerPicker({ value, onChange, ...rest }: PickerProps) {
  const { t } = useTranslation("jobs");
  const current = useCustomer(value || null);
  return <Combobox {...rest} value={value} onChange={(v) => onChange(v)} search={searchCustomers} selectedLabel={current.data?.name} placeholder={t("pick.customer")} clearable />;
}

export function AssetPicker({ value, onChange, ...rest }: PickerProps) {
  const { t } = useTranslation("jobs");
  const current = useAsset(value || null);
  return <Combobox {...rest} value={value} onChange={(v) => onChange(v)} search={searchAssets} selectedLabel={current.data?.label} placeholder={t("pick.item")} clearable />;
}

export function ProductPicker({ value, onChange, services, ...rest }: PickerProps & { services?: boolean }) {
  const { t } = useTranslation("jobs");
  const current = useProduct(value || null);
  return (
    <Combobox {...rest} value={value} onChange={(v) => onChange(v)} search={services ? searchServiceItems : searchProducts}
      selectedLabel={current.data ? `${current.data.name} (${current.data.sku})` : undefined} placeholder={services ? t("pick.service") : t("pick.product")} clearable={services} />
  );
}

/** Staff who can be put in charge of a job or a task. */
export function PersonSelect({ value, onChange, id, none, disabled }: PickerProps & { none?: string }) {
  const { t } = useTranslation("jobs");
  const people = usePeople();
  return (
    <Select id={id} value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
      <option value="">{none ?? t("pick.nobody")}</option>
      {(people.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
    </Select>
  );
}
