import { useState } from "react";

import { PageHeader, Tabs, useTranslation } from "@/sdk";

import HistoryTab from "../actions/HistoryTab";
import WaitingTab from "../actions/WaitingTab";

type Tab = "waiting" | "history";

/** Everything Intelligence has prepared: what waits for this person, and what was decided before. */
export default function ActionsPage() {
  const { t } = useTranslation("intel");
  const [tab, setTab] = useState<Tab>("waiting");
  return (
    <>
      <PageHeader title={t("actionsPage.title")} description={t("actionsPage.hint")} back={{ to: "/intelligence", label: t("today.title") }} />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "waiting", label: t("actionsPage.waiting") }, { id: "history", label: t("actionsPage.history") }]} />
      {tab === "waiting" ? <WaitingTab /> : <HistoryTab />}
    </>
  );
}
