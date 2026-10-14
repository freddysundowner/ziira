import { Link } from "react-router-dom";

import { api, Button, DataTable, money, StatusBadge, unwrap, useQuery, useTranslation } from "@/sdk";

import type { Run } from "../lib/types";

/** Every payslip of a run, with the figures the run was calculated from. */
export function PayslipsPanel({ run, currency }: { run: Run; currency?: string }) {
  const { t } = useTranslation("people");
  const slips = useQuery({ queryKey: ["people", "run", run.id, "payslips", run.status], queryFn: () => unwrap(api.GET("/api/v1/people/payroll-runs/{run_id}/payslips", { params: { path: { run_id: run.id } } })) });
  return (
    <DataTable
      rows={slips.data} loading={slips.isLoading} error={slips.error?.message} onRetry={() => void slips.refetch()} rowKey={(p) => p.id}
      searchText={(p) => `${p.full_name} ${p.employee_no}`} searchPlaceholder={t("employees.search")} pageSize={25}
      empty={{ title: t("run.noPayslips"), hint: t("run.noPayslipsHint") }}
      columns={[
        { header: t("employee.no"), hideBelow: "md", sortValue: (p) => p.employee_no, cell: (p) => <span className="font-mono text-xs">{p.employee_no}</span> },
        { header: t("employee.fullName"), sortValue: (p) => p.full_name, cell: (p) => <Link className="font-medium hover:underline" to={`/payslips/${p.id}`}>{p.full_name}</Link> },
        { header: t("payslip.gross"), align: "right", hideBelow: "sm", sortValue: (p) => Number(p.gross_pay), cell: (p) => money(p.gross_pay, currency) },
        { header: t("payslip.deductions"), align: "right", hideBelow: "md", sortValue: (p) => Number(p.total_deductions), cell: (p) => money(p.total_deductions, currency) },
        { header: t("payslip.net"), align: "right", sortValue: (p) => Number(p.net_pay), cell: (p) => <span className="font-semibold">{money(p.net_pay, currency)}</span> },
        { header: t("payslip.employerCost"), align: "right", hideBelow: "lg", cell: (p) => money(p.employer_cost, currency) },
        { header: t("status"), hideBelow: "lg", cell: (p) => <StatusBadge status={p.status} /> },
        { header: "", align: "right", cell: (p) => <Link to={`/payslips/${p.id}`}><Button size="sm" variant="ghost">{t("open")}</Button></Link> },
      ]}
    />
  );
}
