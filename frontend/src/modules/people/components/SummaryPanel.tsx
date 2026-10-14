import { useState } from "react";
import { Link } from "react-router-dom";

import { api, Badge, DataTable, Input, unwrap, useQuery, useTranslation, today } from "@/sdk";

import { monthBounds } from "../lib/calendar";
import { hoursText } from "../lib/time";

/** Days present, hours and overtime per employee for a month: what payroll reads. */
export function SummaryPanel({ companyId }: { companyId: string }) {
  const { t } = useTranslation("people");
  const [month, setMonth] = useState(today().slice(0, 7));
  const { from, to } = monthBounds(month || today().slice(0, 7));
  const summary = useQuery({
    enabled: !!companyId && !!month,
    queryKey: ["people", "attendance-summary", companyId, from, to],
    queryFn: () => unwrap(api.GET("/api/v1/people/attendance/summary", { params: { query: { company_id: companyId, date_from: from, date_to: to } } })),
  });
  const hours = (summary.data ?? []).reduce((n, r) => n + Number(r.hours), 0);
  const overtime = (summary.data ?? []).reduce((n, r) => n + Number(r.overtime_hours), 0);

  return (
    <DataTable
      rows={summary.data} loading={summary.isLoading} error={summary.error?.message} onRetry={() => void summary.refetch()} rowKey={(r) => r.employee_id}
      searchText={(r) => `${r.full_name} ${r.employee_no}`} searchPlaceholder={t("employees.search")} pageSize={25}
      toolbar={<>
        <Input type="month" aria-label={t("attendance.month")} className="w-auto" value={month} onChange={(e) => setMonth(e.target.value)} />
        {summary.data && <Badge>{t("attendance.monthTotals", { hours: hoursText(hours), overtime: hoursText(overtime) })}</Badge>}
      </>}
      empty={{ title: t("attendance.emptySummary"), hint: t("attendance.emptySummaryHint") }}
      columns={[
        { header: t("employee.no"), hideBelow: "sm", sortValue: (r) => r.employee_no, cell: (r) => <span className="font-mono text-xs">{r.employee_no}</span> },
        { header: t("attendance.employee"), sortValue: (r) => r.full_name, cell: (r) => <Link className="font-medium hover:underline" to={`/employees/${r.employee_id}`}>{r.full_name}</Link> },
        { header: t("attendance.days"), align: "right", sortValue: (r) => r.days, cell: (r) => r.days },
        { header: t("attendance.hours"), align: "right", sortValue: (r) => Number(r.hours), cell: (r) => hoursText(r.hours) },
        { header: t("attendance.overtime"), align: "right", sortValue: (r) => Number(r.overtime_hours), cell: (r) => hoursText(r.overtime_hours) },
      ]}
    />
  );
}
