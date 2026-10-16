import { useState } from "react";
import { Navigate, useSearchParams } from "react-router-dom";

import { PageHeader, Tabs, useCan, useSession, useTranslation } from "@/sdk";

import { useSelectedCompany } from "../components/useSelectedCompany";
import AiTab from "./settings/AiTab";
import NumberingTab from "./settings/NumberingTab";
import PoliciesTab from "./settings/PoliciesTab";
import ReasonsTab from "./settings/ReasonsTab";
import SecurityTab from "./settings/SecurityTab";

type Tab = "policies" | "numbering" | "reasons" | "security" | "ai";

export default function SettingsPage() {
  const { t } = useTranslation("kernel");
  const { enabledUnits } = useSession();
  // The AI assistant belongs to Intelligence: its tab exists only where that is on and the person is an Owner.
  const canManageAi = useCan("ai.manage");
  const hasAi = enabledUnits.has("intel") && canManageAi;
  const [params] = useSearchParams();
  const wanted = params.get("tab");
  const [tab, setTab] = useState<Tab>(wanted === "ai" && hasAi ? "ai" : "policies");
  const { companyId, picker } = useSelectedCompany(t("company"));
  const tabs: { id: Tab; label: string }[] = [
    { id: "policies", label: t("tabPolicies") }, { id: "numbering", label: t("tabNumbering") }, { id: "reasons", label: t("tabReasons") }, { id: "security", label: t("tabSecurity") },
    ...(hasAi ? [{ id: "ai" as const, label: t("tabAi") }] : []),
  ];
  // How much Ziira does for you moved to Intelligence settings: old links to this tab arrive there.
  if (wanted === "actions") return <Navigate to="/intelligence/how-much" replace />;
  return (
    <>
      <PageHeader title={t("settings")} description={t("settingsHint")} />
      {(tab === "policies" || tab === "ai") && picker && <div className="mb-4">{picker}</div>}
      <Tabs value={tab} onChange={setTab} tabs={tabs} />
      {tab === "policies" && <PoliciesTab companyId={companyId} />}
      {tab === "numbering" && <NumberingTab />}
      {tab === "reasons" && <ReasonsTab />}
      {tab === "security" && <SecurityTab />}
      {tab === "ai" && hasAi && <AiTab companyId={companyId} />}
    </>
  );
}
