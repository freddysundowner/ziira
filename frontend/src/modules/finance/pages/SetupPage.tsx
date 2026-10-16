import { useState } from "react";

import { PageHeader, Tabs, useTranslation } from "@/sdk";

import { PeriodsTab } from "../components/PeriodsTab";
import { RulesTab } from "../components/RulesTab";
import { ScopeSelects, useScope } from "../scope";

/** Books setup: accounting periods (close and lock) and the posting rules that say which account each kind of document line uses. */
export default function SetupPage() {
  const { t } = useTranslation("finance");
  const scope = useScope();
  const [tab, setTab] = useState<"periods" | "rules">("periods");
  return (
    <>
      <PageHeader title={t("menu.setup")} description={t("setup.hint")} actions={<ScopeSelects scope={scope} branch={false} />} />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "periods", label: t("periods.title") }, { id: "rules", label: t("rules.title") }]} />
      {tab === "periods" ? <PeriodsTab companyId={scope.companyId} /> : <RulesTab companyId={scope.companyId} />}
    </>
  );
}
