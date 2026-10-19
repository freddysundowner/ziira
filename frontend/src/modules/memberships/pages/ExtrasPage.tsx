import { useState } from "react";

import { PageHeader, Tabs, useTranslation } from "@/sdk";

import { LockersTab } from "../components/LockersTab";
import { TrainersTab } from "../components/TrainersTab";
import { VouchersTab } from "../components/VouchersTab";

type Tab = "lockers" | "vouchers" | "trainers";

/** Things sold or lent around the club: lockers, vouchers and credit, and what trainers earn. */
export default function ExtrasPage() {
  const { t } = useTranslation("memberships");
  const [tab, setTab] = useState<Tab>("lockers");
  return (
    <>
      <PageHeader title={t("extrasMenu")} description={t("extras.hint")} />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "lockers", label: t("extras.tabs.lockers") }, { id: "vouchers", label: t("extras.tabs.vouchers") }, { id: "trainers", label: t("extras.tabs.trainers") }]} />
      {tab === "lockers" && <LockersTab />}
      {tab === "vouchers" && <VouchersTab />}
      {tab === "trainers" && <TrainersTab />}
    </>
  );
}
