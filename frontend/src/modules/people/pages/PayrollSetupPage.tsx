import { useState } from "react";

import { PageHeader, Tabs, useTranslation } from "@/sdk";

import { CompanySelect } from "../components/CompanySelect";
import { ComponentsPanel } from "../components/ComponentsPanel";
import { RulesPanel } from "../components/RulesPanel";
import { useScope } from "../lib/lookups";

/** Payroll setup: the statutory rules the business defines (taxes, contributions, levies) and the pay components. */
export default function PayrollSetupPage() {
  const { t } = useTranslation("people");
  const scope = useScope();
  const [tab, setTab] = useState("rules");
  return (
    <>
      <PageHeader title={t("setup.title")} description={t("setup.hint")} actions={<CompanySelect companies={scope.companies} value={scope.companyId} onChange={scope.setCompanyId} />} />
      <Tabs tabs={[{ id: "rules", label: t("rules.title") }, { id: "components", label: t("component.title") }]} value={tab} onChange={setTab} />
      {tab === "rules" && <RulesPanel companyId={scope.companyId} currency={scope.currency} />}
      {tab === "components" && <ComponentsPanel companyId={scope.companyId} />}
    </>
  );
}
