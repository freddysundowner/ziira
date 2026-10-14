import { useState } from "react";
import { useParams } from "react-router-dom";

import { api, ErrorState, PageHeader, Skeleton, StatusBadge, Tabs, unwrap, useCan, useCompany, useQuery, useSession, useTranslation } from "@/sdk";

import { AttendanceTab } from "../components/AttendanceTab";
import { BankCard } from "../components/BankCard";
import { LeaveTab } from "../components/LeaveTab";
import { PayItemsCard } from "../components/PayItemsCard";
import { PayslipsTab } from "../components/PayslipsTab";
import { ProfileTab } from "../components/ProfileTab";
import { TermsCard } from "../components/TermsCard";

/** One employee: profile and ids, pay (terms, items, payment details), leave, attendance and payslips. */
export default function EmployeePage() {
  const { t } = useTranslation("people");
  const { employeeId = "" } = useParams();
  const me = useSession().me?.user_id;
  const canPay = useCan("employee.pay_edit");
  const canAttendance = useCan("attendance.manage");
  const canPayroll = useCan("payroll.view");
  const { companies } = useCompany();
  const [tab, setTab] = useState("profile");
  const employee = useQuery({ queryKey: ["people", "employee", employeeId], queryFn: () => unwrap(api.GET("/api/v1/people/employees/{employee_id}", { params: { path: { employee_id: employeeId } } })) });
  const e = employee.data;

  if (employee.error) return <ErrorState title={t("employee.notFound")} message={employee.error.message} onRetry={() => void employee.refetch()} />;
  if (!e) return <Skeleton className="h-40 w-full" />;
  const company = companies.find((c) => c.id === e.company_id);
  const branchName = company?.branches.find((b) => b.id === e.branch_id)?.name ?? "—";
  const isSelf = e.user_id !== null && e.user_id === me;
  const tabs = [
    { id: "profile", label: t("employee.profile") },
    ...(canPay ? [{ id: "pay", label: t("employee.pay") }] : []),
    { id: "leave", label: t("leave.title") },
    ...(canAttendance ? [{ id: "attendance", label: t("attendance.title") }] : []),
    ...(canPayroll || isSelf ? [{ id: "payslips", label: t("employee.payslips") }] : []),
  ];

  return (
    <>
      <PageHeader back={{ to: "/employees", label: t("employees.back") }} title={e.full_name}
        description={<span className="flex flex-wrap items-center gap-2"><span className="font-mono">{e.employee_no}</span><StatusBadge status={e.status} />{branchName !== "—" && <span>{branchName}</span>}</span>} />
      <Tabs tabs={tabs} value={tab} onChange={setTab} />
      {tab === "profile" && <ProfileTab employee={e} branchName={branchName} />}
      {tab === "pay" && (
        <div className="space-y-4">
          <TermsCard employee={e} currency={company?.currency} />
          <PayItemsCard employee={e} currency={company?.currency} />
          <BankCard employee={e} />
        </div>
      )}
      {tab === "leave" && <LeaveTab employee={e} />}
      {tab === "attendance" && <AttendanceTab employee={e} />}
      {tab === "payslips" && <PayslipsTab employee={e} currency={company?.currency} />}
    </>
  );
}
