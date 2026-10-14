import { Select, useTranslation } from "@/sdk";

/** A company picker, shown only when the user can reach more than one company. */
export function CompanySelect({ companies, value, onChange }: { companies: { id: string; name: string }[]; value: string; onChange: (id: string) => void }) {
  const { t } = useTranslation("people");
  if (companies.length < 2) return null;
  return (
    <Select aria-label={t("company")} className="w-auto max-w-[14rem]" value={value} onChange={(e) => onChange(e.target.value)}>
      {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
    </Select>
  );
}
