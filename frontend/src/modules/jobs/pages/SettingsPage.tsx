import { useState } from "react";

import { PageHeader, Skeleton, Tabs, useTranslation } from "@/sdk";

import { ChecklistsTab } from "../components/ChecklistsTab";
import { BaysCard } from "../components/BaysCard";
import { GettingStarted } from "../components/GettingStarted";
import { JobTypesTab } from "../components/JobTypesTab";
import { WorkshopCatalog } from "../components/WorkshopCatalog";
import { RatesTab } from "../components/RatesTab";
import { StagesTab } from "../components/StagesTab";
import { useJobsCompany } from "../hooks";

type Tab = "start" | "stages" | "checklists" | "rates" | "workshop" | "types" | "bays";
const TABS: Tab[] = ["start", "stages", "checklists", "types", "workshop", "bays", "rates"];

/** How this business works its jobs: the stages, the intake checklists, the rates and the two invoice items. */
export default function SettingsPage() {
  const { t } = useTranslation("jobs");
  const { companyId, currency, isLoading, branches } = useJobsCompany();
  const [tab, setTab] = useState<Tab>("stages");
  return (
    <>
      <PageHeader title={t("menu.settings")} description={t("settings.hint")} />
      <Tabs tabs={TABS.map((id) => ({ id, label: t(`settings.tabs.${id}`) }))} value={tab} onChange={setTab} />
      {isLoading || !companyId ? <Skeleton className="h-64" /> : (
        <>
          {tab === "start" && <GettingStarted companyId={companyId} />}
          {tab === "types" && <JobTypesTab companyId={companyId} />}
          {tab === "workshop" && <WorkshopCatalog companyId={companyId} currency={currency} />}
          {tab === "bays" && <BaysCard companyId={companyId} branches={branches} />}
          {tab === "stages" && <StagesTab companyId={companyId} />}
          {tab === "checklists" && <ChecklistsTab companyId={companyId} />}
          {tab === "rates" && <RatesTab companyId={companyId} currency={currency} />}
        </>
      )}
    </>
  );
}
