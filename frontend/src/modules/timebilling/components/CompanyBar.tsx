import { Select, useTranslation } from "@/sdk";

/** The company picker, shown only when the person can reach more than one. */
export function CompanyPicker({ companies, value, onChange }: { companies: { id: string; name: string }[]; value: string; onChange: (id: string) => void }) {
  const { t } = useTranslation("timebilling");
  if (companies.length < 2) return null;
  return (
    <Select className="w-48" aria-label={t("company")} value={value} onChange={(e) => onChange(e.target.value)}>
      {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
    </Select>
  );
}
