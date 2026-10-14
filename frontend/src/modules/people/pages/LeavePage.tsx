import { useState } from "react";

import { PageHeader, Tabs, useTranslation } from "@/sdk";

import { CompanySelect } from "../components/CompanySelect";
import { OverviewPanel } from "../components/OverviewPanel";
import { RequestsPanel } from "../components/RequestsPanel";
import { TypesPanel } from "../components/TypesPanel";
import { useEmployeeDirectory, useLeaveTypes, useScope } from "../lib/lookups";

/** Leave: requests to decide (by someone other than the person asking), a month overview, and the kinds of leave. */
export default function LeavePage() {
  const { t } = useTranslation("people");
  const scope = useScope();
  const [tab, setTab] = useState("requests");
  const directory = useEmployeeDirectory(scope.companyId);
  const types = useLeaveTypes(scope.companyId);
  return (
    <>
      <PageHeader title={t("leave.title")} description={t("leave.hint")} actions={<CompanySelect companies={scope.companies} value={scope.companyId} onChange={scope.setCompanyId} />} />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "requests", label: t("leave.requests") }, { id: "overview", label: t("leave.overview") }, { id: "types", label: t("leave.types") }]} />
      {tab === "requests" && <RequestsPanel companyId={scope.companyId} types={types.data ?? []} names={directory.name} />}
      {tab === "overview" && <OverviewPanel types={types.data ?? []} names={directory.name} />}
      {tab === "types" && <TypesPanel companyId={scope.companyId} types={types.data} loading={types.isLoading} error={types.error?.message} onRetry={() => void types.refetch()} />}
    </>
  );
}
