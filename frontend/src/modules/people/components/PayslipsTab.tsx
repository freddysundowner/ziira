import { useState } from "react";
import { Link } from "react-router-dom";

import { api, Card, DataTable, EmptyState, ErrorState, money, Select, Skeleton, unwrap, useQuery, useSession, useTranslation, formatDate, Button } from "@/sdk";

import { useRules } from "../lib/lookups";
import type { Employee, TaxCard } from "../lib/types";
import { DownloadButton } from "./DownloadButton";

/** The employee's yearly tax card (pay and what each rule took, month by month) and, for the person themselves, their payslips. */
export function PayslipsTab({ employee, currency }: { employee: Employee; currency?: string }) {
  const { t } = useTranslation("people");
  const me = useSession().me?.user_id;
  const thisYear = new Date().getFullYear();
  const [year, setYear] = useState(thisYear);
  const rules = useRules(employee.company_id);
  const ruleName = (code: string) => String((rules.data?.find((r) => r.code === code)?.definition as { name?: string } | undefined)?.name ?? code);
  const card = useQuery({
    queryKey: ["people", "tax-card", employee.id, year],
    // The generated type for this endpoint is empty because it can also answer with CSV, so the JSON shape is named here.
    queryFn: async () => (await unwrap(api.GET("/api/v1/people/employees/{employee_id}/tax-card", { params: { path: { employee_id: employee.id }, query: { year } } }))) as TaxCard,
  });
  const own = employee.user_id !== null && employee.user_id === me;
  const mine = useQuery({ enabled: own, queryKey: ["people", "my-payslips"], queryFn: () => unwrap(api.GET("/api/v1/people/me/payslips")) });

  return (
    <div className="space-y-4">
      {own && (
        <Card title={t("payslip.mine")} flush>
          <DataTable rows={mine.data} loading={mine.isLoading} error={mine.error?.message} onRetry={() => void mine.refetch()} rowKey={(p) => p.id}
            empty={{ title: t("payslip.noneYet") }}
            columns={[
              { header: t("payslip.gross"), align: "right", cell: (p) => money(p.gross_pay, currency) },
              { header: t("payslip.net"), align: "right", cell: (p) => <span className="font-semibold">{money(p.net_pay, currency)}</span> },
              { header: "", align: "right", cell: (p) => <Link to={`/payslips/${p.id}`}><Button size="sm" variant="secondary">{t("open")}</Button></Link> },
            ]} />
        </Card>
      )}
      <Card title={t("taxCard.title")} description={t("taxCard.hint")} flush actions={<>
        <Select aria-label={t("leave.year")} className="w-auto" value={year} onChange={(e) => setYear(Number(e.target.value))}>
          {[thisYear, thisYear - 1, thisYear - 2, thisYear - 3].map((y) => <option key={y} value={y}>{y}</option>)}
        </Select>
        <DownloadButton size="sm" fileName={`tax-card-${employee.employee_no}-${year}.csv`}
          request={() => api.GET("/api/v1/people/employees/{employee_id}/tax-card", { params: { path: { employee_id: employee.id }, query: { year, format: "csv" } }, parseAs: "blob" })}>{t("csv")}</DownloadButton>
      </>}>
        {card.error ? <ErrorState message={card.error.message} onRetry={() => void card.refetch()} />
          : !card.data ? <Skeleton className="m-4 h-32" />
          : card.data.rows.length === 0 ? <EmptyState title={t("taxCard.empty", { year })} hint={t("taxCard.emptyHint")} />
          : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-line bg-sunken/60 text-xs uppercase tracking-wide text-muted">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">{t("period")}</th>
                    <th className="px-4 py-2.5 text-right font-medium">{t("payslip.gross")}</th>
                    <th className="px-4 py-2.5 text-right font-medium">{t("payslip.benefits")}</th>
                    <th className="px-4 py-2.5 text-right font-medium">{t("payslip.taxable")}</th>
                    {card.data.rules.map((c) => <th key={c} className="px-4 py-2.5 text-right font-medium">{ruleName(c)}</th>)}
                    <th className="px-4 py-2.5 text-right font-medium">{t("payslip.deductions")}</th>
                    <th className="px-4 py-2.5 text-right font-medium">{t("payslip.net")}</th>
                  </tr>
                </thead>
                <tbody className="tnum divide-y divide-line">
                  {[...card.data.rows, ...(card.data.totals ? [card.data.totals] : [])].map((r, i, all) => {
                    const total = card.data && i === all.length - 1 && !!card.data.totals;
                    return (
                      <tr key={`${r.period_start}-${i}`} className={total ? "bg-sunken/60 font-semibold" : undefined}>
                        <td className="px-4 py-2.5">{total ? t("taxCard.total") : formatDate(r.period_start)}</td>
                        <td className="px-4 py-2.5 text-right">{money(r.gross_pay, currency)}</td>
                        <td className="px-4 py-2.5 text-right">{money(r.benefits, currency)}</td>
                        <td className="px-4 py-2.5 text-right">{money(r.taxable_pay, currency)}</td>
                        {card.data!.rules.map((c) => <td key={c} className="px-4 py-2.5 text-right">{money(r.by_rule[c] ?? "0", currency)}</td>)}
                        <td className="px-4 py-2.5 text-right">{money(r.total_deductions, currency)}</td>
                        <td className="px-4 py-2.5 text-right">{money(r.net_pay, currency)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
      </Card>
      <p className="text-xs text-muted">{t("payslip.findHint")} <Link className="font-medium text-brand underline" to="/payroll">{t("payroll.title")}</Link></p>
    </div>
  );
}
