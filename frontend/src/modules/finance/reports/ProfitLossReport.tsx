import { useState } from "react";

import { api, Badge, Card, Checkbox, formatDate, type Schemas, useQuery, useTranslation } from "@/sdk";

import { json } from "../api";
import { CsvButton } from "../components/CsvButton";
import { ReportFrame } from "../components/ReportFrame";
import { StatementRows, StatementTable } from "../components/Statement";
import type { ReportProps } from "./types";

export function ProfitLossReport({ scope, from, to }: ReportProps) {
  const { t } = useTranslation("finance");
  const [byBranch, setByBranch] = useState(false);
  const query = { company_id: scope.companyId, date_from: from, date_to: to, branch_id: scope.branchId || undefined, by_branch: byBranch };
  const report = useQuery({
    enabled: !!scope.companyId, queryKey: ["finance", "pnl", query],
    queryFn: () => json<Schemas["ProfitReportOut"]>(api.GET("/api/v1/finance/reports/profit-and-loss", { params: { query } })),
  });
  const data = report.data;
  return (
    <div className="space-y-4">
      <ReportFrame title={t("reports.pnl")} company={scope.company?.name ?? ""} period={`${formatDate(from)} – ${formatDate(to)}`}
        loading={report.isLoading} error={report.error?.message} onRetry={() => void report.refetch()}
        actions={<>
          {scope.branches.length > 1 && !scope.branchId && <Checkbox label={t("splitByBranch")} checked={byBranch} onChange={(e) => setByBranch(e.target.checked)} />}
          <CsvButton fallbackName="profit-and-loss.csv" request={() => api.GET("/api/v1/finance/reports/profit-and-loss", { params: { query: { ...query, format: "csv" } }, parseAs: "blob" })} />
        </>}>
        {data && <Pnl statement={data.consolidated} currency={scope.currency} />}
      </ReportFrame>
      {data && byBranch && data.branches.map((b) => (
        <Card key={b.branch_id ?? "none"} title={b.branch_name || t("noBranch")} description={b.branch_id ? undefined : t("noBranchHint")}>
          <Pnl statement={b.statement} currency={scope.currency} />
        </Card>
      ))}
    </div>
  );
}

function Pnl({ statement: s, currency }: { statement: Schemas["ProfitAndLossOut"]; currency?: string }) {
  const { t } = useTranslation("finance");
  const loss = Number(s.net_profit) < 0;
  return (
    <>
      <StatementTable>
        <StatementRows title={t("income")} lines={s.income} total={s.total_income} totalLabel={t("totalIncome")} currency={currency} />
        <StatementRows title={t("costOfSales")} lines={s.cost_of_sales} total={s.total_cost_of_sales} totalLabel={t("totalCostOfSales")} currency={currency} />
        <StatementRows total={s.gross_profit} totalLabel={t("grossProfit")} currency={currency} />
        <StatementRows title={t("operatingExpenses")} lines={s.expenses} total={s.total_expenses} totalLabel={t("totalExpenses")} currency={currency} />
        <StatementRows total={s.net_profit} totalLabel={loss ? t("netLoss") : t("netProfit")} currency={currency} emphasis={loss ? "bad" : "ok"} />
      </StatementTable>
      {s.income.length + s.cost_of_sales.length + s.expenses.length === 0 && <p className="mt-3"><Badge>{t("nothingPosted")}</Badge></p>}
    </>
  );
}
