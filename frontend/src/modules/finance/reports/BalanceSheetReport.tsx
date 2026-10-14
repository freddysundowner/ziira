import { api, Alert, formatDate, type Schemas, useQuery, useTranslation } from "@/sdk";

import { json } from "../api";
import { CsvButton } from "../components/CsvButton";
import { ReportFrame } from "../components/ReportFrame";
import { StatementRows, StatementTable } from "../components/Statement";
import type { ReportProps } from "./types";

export function BalanceSheetReport({ scope, to }: ReportProps) {
  const { t } = useTranslation("finance");
  const query = { company_id: scope.companyId, as_of: to, branch_id: scope.branchId || undefined };
  const report = useQuery({
    enabled: !!scope.companyId, queryKey: ["finance", "balance-sheet", query],
    queryFn: () => json<Schemas["BalanceSheetOut"]>(api.GET("/api/v1/finance/reports/balance-sheet", { params: { query } })),
  });
  const s = report.data;
  const c = scope.currency;
  return (
    <ReportFrame title={t("reports.balance")} company={scope.company?.name ?? ""} period={t("asOf", { date: formatDate(to) })}
      loading={report.isLoading} error={report.error?.message} onRetry={() => void report.refetch()}
      actions={<CsvButton fallbackName="balance-sheet.csv" request={() => api.GET("/api/v1/finance/reports/balance-sheet", { params: { query: { ...query, format: "csv" } }, parseAs: "blob" })} />}>
      {s && (
        <div className="space-y-3">
          {!s.balanced && <Alert tone="bad">{t("notBalanced")}</Alert>}
          <StatementTable>
            <StatementRows title={t("assets")} lines={s.assets} total={s.total_assets} totalLabel={t("totalAssets")} currency={c} />
            <StatementRows title={t("liabilities")} lines={s.liabilities} total={s.total_liabilities} totalLabel={t("totalLiabilities")} currency={c} />
            <StatementRows title={t("equity")} lines={s.equity} currency={c} />
            <StatementRows total={s.accumulated_profit} totalLabel={t("unclosedProfit")} currency={c} />
            <StatementRows total={s.total_equity} totalLabel={t("totalEquity")} currency={c} />
            <StatementRows total={s.total_liabilities_and_equity} totalLabel={t("totalLiabilitiesEquity")} currency={c} />
          </StatementTable>
        </div>
      )}
    </ReportFrame>
  );
}
