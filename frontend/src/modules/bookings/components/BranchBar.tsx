import { Select, useTranslation } from "@/sdk";

/** The branch picker, shown only when the business has more than one. */
export function BranchPicker({ branches, value, onChange }: { branches: { id: string; name: string }[]; value: string; onChange: (id: string) => void }) {
  const { t } = useTranslation("bookings");
  if (branches.length < 2) return null;
  return (
    <Select className="w-44" aria-label={t("branch")} value={value} onChange={(e) => onChange(e.target.value)}>
      {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
    </Select>
  );
}
