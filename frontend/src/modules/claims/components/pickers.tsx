import { Combobox, Select, useTranslation } from "@/sdk";

import { searchCustomers, searchServiceItems, useCustomer, usePayers } from "../hooks";

interface PickerProps {
  value: string;
  onChange: (id: string) => void;
  id?: string;
  invalid?: boolean;
  disabled?: boolean;
}

export function CustomerPicker({ value, onChange, ...rest }: PickerProps) {
  const { t } = useTranslation("claims");
  const current = useCustomer(value || null);
  return <Combobox {...rest} value={value} onChange={(v) => onChange(v)} search={searchCustomers} selectedLabel={current.data?.name} placeholder={t("pick.customer")} clearable />;
}

export function ServiceItemPicker({ value, onChange, ...rest }: PickerProps) {
  const { t } = useTranslation("claims");
  return <Combobox {...rest} value={value} onChange={(v) => onChange(v)} search={searchServiceItems} placeholder={t("pick.serviceItem")} clearable />;
}

/** The payers a company has set up (active ones by default). */
export function PayerSelect({ companyId, value, onChange, id, all, invalid, disabled, onlyActive = true }: PickerProps & { companyId: string; all?: string; onlyActive?: boolean }) {
  const { t } = useTranslation("claims");
  const payers = usePayers(companyId, onlyActive);
  return (
    <Select id={id} value={value} invalid={invalid} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
      <option value="">{all ?? t("pick.payer")}</option>
      {(payers.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
    </Select>
  );
}
