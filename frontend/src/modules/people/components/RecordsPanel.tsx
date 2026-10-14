import { Plus } from "lucide-react";
import { useState } from "react";

import { api, Button, DataTable, formatDate, Input, monthStart, Pager, Select, today, unwrap, usePagedList, useTranslation } from "@/sdk";

import { useAttendanceColumns } from "./useAttendanceColumns";
import { AttendanceDrawer } from "./AttendanceDrawer";
import { EmployeePicker } from "./EmployeePicker";
import type { Attendance } from "../lib/types";

export function RecordsPanel({ companyId, branches, names }: { companyId: string; branches: { id: string; name: string }[]; names: (id: string) => string }) {
  const { t } = useTranslation("people");
  const [from, setFrom] = useState(today());
  const [to, setTo] = useState(today());
  const [branch, setBranch] = useState("");
  const [employee, setEmployee] = useState("");
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<Attendance | undefined>();
  const columns = useAttendanceColumns(setEditing);
  const list = usePagedList(["people", "attendance", companyId, from, to, branch, employee], (limit, offset) =>
    unwrap(api.GET("/api/v1/people/attendance", { params: { query: { date_from: from, date_to: to, branch_id: branch || undefined, employee_id: employee || undefined, limit, offset } } })), 50);

  return (
    <>
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(r) => r.id}
        toolbar={<>
          <Input type="date" aria-label={t("from")} className="w-auto" value={from} max={to} onChange={(e) => setFrom(e.target.value)} />
          <Input type="date" aria-label={t("to")} className="w-auto" value={to} min={from} onChange={(e) => setTo(e.target.value)} />
          <Button variant="ghost" size="sm" onClick={() => { setFrom(today()); setTo(today()); }}>{t("today")}</Button>
          <Button variant="ghost" size="sm" onClick={() => { setFrom(monthStart()); setTo(today()); }}>{t("thisMonth")}</Button>
          {branches.length > 1 && (
            <Select aria-label={t("branch")} className="w-auto" value={branch} onChange={(e) => setBranch(e.target.value)}>
              <option value="">{t("allBranches")}</option>{branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </Select>
          )}
          <div className="w-52"><EmployeePicker companyId={companyId} value={employee} onChange={setEmployee} placeholder={t("attendance.anyone")} /></div>
          <Button className="ml-auto" onClick={() => setAdding(true)}><Plus className="h-4 w-4" />{t("attendance.new")}</Button>
        </>}
        empty={{ title: t("attendance.emptyRange"), hint: t("attendance.emptyRangeHint"), action: <Button onClick={() => setAdding(true)}>{t("attendance.new")}</Button> }}
        columns={[
          { header: t("attendance.employee"), sortValue: (r) => names(r.employee_id), cell: (r) => <span className="font-medium">{names(r.employee_id)}</span> },
          { header: t("attendance.date"), sortValue: (r) => r.work_date, cell: (r) => formatDate(r.work_date) },
          ...columns,
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
      <AttendanceDrawer open={adding} onClose={() => setAdding(false)} companyId={companyId} />
      <AttendanceDrawer open={!!editing} onClose={() => setEditing(undefined)} companyId={companyId} record={editing} />
    </>
  );
}
