import { Plus } from "lucide-react";
import { useState } from "react";

import { api, Badge, Button, Card, DataTable, formatDate, Input, monthStart, today, unwrap, useQuery, useTranslation } from "@/sdk";

import { hoursText } from "../lib/time";
import type { Attendance, Employee } from "../lib/types";
import { AttendanceDrawer } from "./AttendanceDrawer";
import { useAttendanceColumns } from "./useAttendanceColumns";

export function AttendanceTab({ employee }: { employee: Employee }) {
  const { t } = useTranslation("people");
  const [from, setFrom] = useState(monthStart());
  const [to, setTo] = useState(today());
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<Attendance | undefined>();
  const columns = useAttendanceColumns(setEditing);
  const rows = useQuery({
    queryKey: ["people", "attendance", "employee", employee.id, from, to],
    queryFn: () => unwrap(api.GET("/api/v1/people/attendance", { params: { query: { employee_id: employee.id, date_from: from, date_to: to, limit: 500 } } })),
  });
  const totalHours = (rows.data ?? []).reduce((sum, r) => sum + Number(r.hours ?? 0), 0);
  const totalOvertime = (rows.data ?? []).reduce((sum, r) => sum + Number(r.overtime_hours), 0);

  return (
    <Card title={t("attendance.title")} flush actions={<Button size="sm" onClick={() => setAdding(true)}><Plus className="h-3.5 w-3.5" />{t("attendance.new")}</Button>}>
      <DataTable
        rows={rows.data} loading={rows.isLoading} error={rows.error?.message} onRetry={() => void rows.refetch()} rowKey={(r) => r.id}
        toolbar={<>
          <Input type="date" aria-label={t("from")} className="w-auto" value={from} max={to} onChange={(e) => setFrom(e.target.value)} />
          <Input type="date" aria-label={t("to")} className="w-auto" value={to} min={from} onChange={(e) => setTo(e.target.value)} />
          {rows.data && <Badge>{t("attendance.totals", { days: rows.data.length, hours: hoursText(totalHours), overtime: hoursText(totalOvertime) })}</Badge>}
        </>}
        empty={{ title: t("attendance.empty"), hint: t("attendance.emptyHint") }}
        columns={[
          { header: t("attendance.date"), sortValue: (r) => r.work_date, cell: (r) => <span className="font-medium">{formatDate(r.work_date)}</span> },
          ...columns,
        ]}
      />
      <AttendanceDrawer open={adding} onClose={() => setAdding(false)} companyId={employee.company_id} employeeId={employee.id} />
      <AttendanceDrawer open={!!editing} onClose={() => setEditing(undefined)} companyId={employee.company_id} record={editing} />
    </Card>
  );
}
