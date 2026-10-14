import { Field, Select, useCompany, useTranslation } from "@/sdk";

/** Company and branch pickers. Each shows only when the person has more than one to choose from. */
export function CompanyBranch({ companyId, branchId, onCompany, onBranch, lockCompany }: {
  companyId: string; branchId: string; onCompany: (id: string) => void; onBranch: (id: string) => void; lockCompany?: boolean;
}) {
  const { t } = useTranslation("purchasing");
  const { companies } = useCompany();
  const branches = companies.find((c) => c.id === companyId)?.branches ?? [];
  return (
    <>
      {companies.length > 1 && (
        <Field label={t("company")}>
          <Select value={companyId} disabled={lockCompany} onChange={(e) => { onCompany(e.target.value); onBranch(""); }}>
            {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </Select>
        </Field>
      )}
      {branches.length > 1 && (
        <Field label={t("branch")}>
          <Select value={branchId} onChange={(e) => onBranch(e.target.value)}>
            <option value="">{t("anyBranch")}</option>
            {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </Select>
        </Field>
      )}
    </>
  );
}
