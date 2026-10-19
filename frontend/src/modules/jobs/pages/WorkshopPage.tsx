import { useState } from "react";

import { PageHeader, Skeleton, Tabs, useTranslation } from "@/sdk";

import { BayBoard } from "../components/BayBoard";
import { CarsOut } from "../components/CarsOut";
import { MyWork } from "../components/MyWork";
import { ServiceDue } from "../components/ServiceDue";
import { Technicians } from "../components/Technicians";
import { useJobsCompany } from "../hooks";

type Tab = "mine" | "bays" | "technicians" | "due" | "cars";
const TABS: Tab[] = ["mine", "bays", "technicians", "due", "cars"];

/** The workshop floor: my jobs today, the bay board, hours booked against billed, services coming due and courtesy cars out. */
export default function WorkshopPage() {
  const { t } = useTranslation("jobs");
  const { companyId, branches, isLoading } = useJobsCompany();
  const [tab, setTab] = useState<Tab>("mine");
  return (
    <>
      <PageHeader title={t("garage.workshop.title")} description={t("garage.workshop.hint")} />
      <Tabs tabs={TABS.map((id) => ({ id, label: t(`garage.workshop.tabs.${id}`) }))} value={tab} onChange={setTab} />
      {isLoading || !companyId ? <Skeleton className="h-64" /> : (
        <div className="mt-4">
          {tab === "mine" && <MyWork companyId={companyId} />}
          {tab === "bays" && <BayBoard companyId={companyId} branches={branches} />}
          {tab === "technicians" && <Technicians companyId={companyId} />}
          {tab === "due" && <ServiceDue companyId={companyId} />}
          {tab === "cars" && <CarsOut companyId={companyId} />}
        </div>
      )}
    </>
  );
}
