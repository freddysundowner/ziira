import { PageHeader, useTranslation } from "@/sdk";

import { CompanySelect } from "../components/CompanySelect";
import { ComponentsPanel } from "../components/ComponentsPanel";
import { useScope } from "../lib/lookups";

/** Pay components on their own, for people who set up employee pay but do not see payroll. */
export default function PayComponentsPage() {
  const { t } = useTranslation("people");
  const scope = useScope();
  return (
    <>
      <PageHeader title={t("component.title")} actions={<CompanySelect companies={scope.companies} value={scope.companyId} onChange={scope.setCompanyId} />} />
      <ComponentsPanel companyId={scope.companyId} />
    </>
  );
}
