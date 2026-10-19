import { useState } from "react";
import { Link } from "react-router-dom";

import { PageHeader, Tabs, useSession, useTranslation } from "@/sdk";

import { useSelectedCompany } from "../components/useSelectedCompany";
import ChannelsTab from "./notifications/ChannelsTab";
import LogTab from "./notifications/LogTab";
import OptOutsTab from "./notifications/OptOutsTab";

type Tab = "log" | "optouts" | "channels";

/** What the business sent by email and SMS, who asked not to be contacted, and which channels are set up. */
export default function NotificationsPage() {
  const { t } = useTranslation("kernel");
  const { enabledUnits } = useSession();
  const [tab, setTab] = useState<Tab>("log");
  const { companyId, picker } = useSelectedCompany(t("company"));
  return (
    <>
      <PageHeader title={t("notifications")} description={t("notificationsHint")}
        actions={enabledUnits.has("messaging") ? <Link className="text-sm font-medium text-brand-strong hover:underline" to="/messaging/channels">{t("setUpChannels")}</Link> : undefined} />
      {picker && <div className="mb-4">{picker}</div>}
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "log", label: t("tabLog") }, { id: "optouts", label: t("tabOptOuts") }, { id: "channels", label: t("tabChannels") }]} />
      {tab === "log" && <LogTab companyId={companyId} />}
      {tab === "optouts" && <OptOutsTab companyId={companyId} />}
      {tab === "channels" && <ChannelsTab companyId={companyId} />}
    </>
  );
}
