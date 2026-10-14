import { useState } from "react";

import { Select, useCompany, useTranslation } from "@/sdk";

/** The company (and optionally branch) a finance screen is looking at. Most businesses have one company, so pickers only appear when there is a choice. */
export function useScope() {
  const { companies, company: first, isLoading } = useCompany();
  const [companyId, setCompanyId] = useState("");
  const [branchId, setBranchId] = useState("");
  const company = companies.find((c) => c.id === companyId) ?? first;
  return {
    loading: isLoading,
    companies,
    company,
    companyId: company?.id ?? "",
    currency: company?.currency,
    branches: company?.branches ?? [],
    branchId,
    setCompany: (id: string) => { setCompanyId(id); setBranchId(""); },
    setBranch: setBranchId,
  };
}
export type Scope = ReturnType<typeof useScope>;

export const branchName = (scope: Pick<Scope, "branches">, id: string | null | undefined): string => scope.branches.find((b) => b.id === id)?.name ?? "—";

/** Company and branch pickers, shown only when the user has more than one to choose from. */
export function ScopeSelects({ scope, branch = true }: { scope: Scope; branch?: boolean }) {
  const { t } = useTranslation("finance");
  return (
    <>
      {scope.companies.length > 1 && (
        <Select aria-label={t("company")} className="w-auto min-w-[10rem]" value={scope.companyId} onChange={(e) => scope.setCompany(e.target.value)}>
          {scope.companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </Select>
      )}
      {branch && scope.branches.length > 1 && (
        <Select aria-label={t("branch")} className="w-auto min-w-[10rem]" value={scope.branchId} onChange={(e) => scope.setBranch(e.target.value)}>
          <option value="">{t("allBranches")}</option>
          {scope.branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
        </Select>
      )}
    </>
  );
}
