import { useState } from "react";

import { PageHeader, Tabs, useTranslation } from "@/sdk";

import { useSelectedCompany } from "../components/useSelectedCompany";
import NumberingTab from "./settings/NumberingTab";
import PoliciesTab from "./settings/PoliciesTab";
import ReasonsTab from "./settings/ReasonsTab";

type Tab = "policies" | "numbering" | "reasons";

export default function SettingsPage() {
  const { t } = useTranslation("kernel");
  const [tab, setTab] = useState<Tab>("policies");
  const { companyId, picker } = useSelectedCompany(t("company"));
  return (
    <>
      <PageHeader title={t("settings")} description={t("settingsHint")} />
      {tab === "policies" && picker && <div className="mb-4">{picker}</div>}
      <Tabs value={tab} onChange={setTab} tabs={[
        { id: "policies", label: t("tabPolicies") }, { id: "numbering", label: t("tabNumbering") }, { id: "reasons", label: t("tabReasons") },
      ]} />
      {tab === "policies" && <PoliciesTab companyId={companyId} />}
      {tab === "numbering" && <NumberingTab />}
      {tab === "reasons" && <ReasonsTab />}
    </>
  );
}
