import { useState } from "react";

import { PageHeader, Tabs, useTranslation } from "@/sdk";

import { CompanySelect } from "../components/CompanySelect";
import { RecordsPanel } from "../components/RecordsPanel";
import { ShiftsPanel } from "../components/ShiftsPanel";
import { SummaryPanel } from "../components/SummaryPanel";
import { useEmployeeDirectory, useScope } from "../lib/lookups";

/** Who worked when: daily records (by hand or from the till), the month's summary payroll reads, and shifts. */
export default function AttendancePage() {
  const { t } = useTranslation("people");
  const scope = useScope();
  const [tab, setTab] = useState("records");
  const directory = useEmployeeDirectory(scope.companyId);
  return (
    <>
      <PageHeader title={t("menu.attendanceLeave")} description={t("attendance.hint")} actions={<CompanySelect companies={scope.companies} value={scope.companyId} onChange={scope.setCompanyId} />} />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "records", label: t("attendance.records") }, { id: "summary", label: t("attendance.summary") }, { id: "shifts", label: t("shift.title") }]} />
      {tab === "records" && <RecordsPanel companyId={scope.companyId} branches={scope.branches} names={directory.name} />}
      {tab === "summary" && <SummaryPanel companyId={scope.companyId} />}
      {tab === "shifts" && <ShiftsPanel companyId={scope.companyId} branches={scope.branches} />}
    </>
  );
}
