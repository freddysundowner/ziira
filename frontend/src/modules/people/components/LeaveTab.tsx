import { Plus } from "lucide-react";
import { useState } from "react";

import { api, Button, Card, DataTable, Select, quantity, unwrap, useQuery, useTranslation } from "@/sdk";

import { useLeaveTypes } from "../lib/lookups";
import type { Employee } from "../lib/types";
import { LeaveRequestDrawer } from "./LeaveRequestDrawer";
import { LeaveTable } from "./LeaveTable";

export function LeaveTab({ employee }: { employee: Employee }) {
  const { t } = useTranslation("people");
  const thisYear = new Date().getFullYear();
  const [year, setYear] = useState(thisYear);
  const [asking, setAsking] = useState(false);
  const types = useLeaveTypes(employee.company_id);
  const balances = useQuery({
    queryKey: ["people", "balances", employee.id, year],
    queryFn: () => unwrap(api.GET("/api/v1/people/employees/{employee_id}/leave-balances", { params: { path: { employee_id: employee.id }, query: { year } } })),
  });
  const requests = useQuery({
    queryKey: ["people", "leave", "employee", employee.id],
    queryFn: () => unwrap(api.GET("/api/v1/people/leave-requests", { params: { query: { employee_id: employee.id, limit: 100 } } })),
  });

  return (
    <div className="space-y-4">
      <Card title={t("leave.balances")} flush actions={<Select aria-label={t("leave.year")} className="w-auto" value={year} onChange={(e) => setYear(Number(e.target.value))}>
        {[thisYear + 1, thisYear, thisYear - 1, thisYear - 2].map((y) => <option key={y} value={y}>{y}</option>)}
      </Select>}>
        <DataTable
          rows={balances.data} loading={balances.isLoading} error={balances.error?.message} onRetry={() => void balances.refetch()} rowKey={(b) => b.leave_type_id}
          empty={{ title: t("leave.noBalances"), hint: t("leave.noBalancesHint") }}
          columns={[
            { header: t("leave.type"), cell: (b) => <span className="font-medium">{b.leave_type}</span> },
            { header: t("leave.paid"), hideBelow: "sm", cell: (b) => (b.is_paid ? t("yes") : t("no")) },
            { header: t("leave.entitled"), align: "right", cell: (b) => (b.days_per_year === null ? t("leave.unlimited") : quantity(b.days_per_year)) },
            { header: t("leave.taken"), align: "right", cell: (b) => quantity(b.taken) },
            { header: t("leave.left"), align: "right", cell: (b) => <span className="font-semibold">{b.left === null ? "—" : quantity(b.left)}</span> },
          ]}
        />
      </Card>
      <Card title={t("leave.requests")} flush actions={<Button size="sm" onClick={() => setAsking(true)}><Plus className="h-3.5 w-3.5" />{t("leave.new")}</Button>}>
        <LeaveTable rows={requests.data} loading={requests.isLoading} error={requests.error?.message} onRetry={() => void requests.refetch()} types={types.data ?? []}
          empty={{ title: t("leave.noRequests"), hint: t("leave.noRequestsHint") }} />
      </Card>
      <LeaveRequestDrawer open={asking} onClose={() => setAsking(false)} companyId={employee.company_id} employeeId={employee.id} />
    </div>
  );
}
