import { api, Alert, formatDate, money, type Schemas, useQuery, useTranslation } from "@/sdk";

import { json } from "../api";
import { CsvButton } from "../components/CsvButton";
import { ReportFrame } from "../components/ReportFrame";
import { StatementTable } from "../components/Statement";
import type { ReportProps } from "./types";

export function CashFlowReport({ scope, from, to }: ReportProps) {
  const { t } = useTranslation("finance");
  const query = { company_id: scope.companyId, date_from: from, date_to: to, branch_id: scope.branchId || undefined };
  const report = useQuery({
    enabled: !!scope.companyId, queryKey: ["finance", "cash-flow", query],
    queryFn: () => json<Schemas["CashFlowOut"]>(api.GET("/api/v1/finance/reports/cash-flow", { params: { query } })),
  });
  const s = report.data;
  const c = scope.currency;
  return (
    <ReportFrame title={t("reports.cashflow")} company={scope.company?.name ?? ""} period={`${formatDate(from)} – ${formatDate(to)}`}
      loading={report.isLoading} error={report.error?.message} onRetry={() => void report.refetch()}
      actions={<CsvButton fallbackName="cash-flow.csv" request={() => api.GET("/api/v1/finance/reports/cash-flow", { params: { query: { ...query, format: "csv" } }, parseAs: "blob" })} />}>
      {s && (
        <div className="space-y-3">
          <p className="text-xs text-muted">{t("cashFlowHint")}</p>
          {!s.reconciles && <Alert tone="bad">{t("notReconciled")}</Alert>}
          <StatementTable>
            <tr><td className="px-4 py-2 font-semibold">{t("openingBalance")}</td><td className="tnum px-4 py-2 text-right font-semibold">{money(s.opening, c)}</td></tr>
            {s.movements.map((m) => (
              <tr key={m.label} className="border-t border-line"><td className="px-4 py-2">{m.label}</td><td className="tnum px-4 py-2 text-right">{money(m.amount, c)}</td></tr>
            ))}
            <tr className="border-t border-line"><td className="px-4 py-2 font-semibold">{t("netMovement")}</td><td className="tnum px-4 py-2 text-right font-semibold">{money(s.net_movement, c)}</td></tr>
            <tr className="border-t border-line"><td className="px-4 py-2 font-semibold">{t("closingBalance")}</td><td className="tnum px-4 py-2 text-right font-semibold">{money(s.closing, c)}</td></tr>
          </StatementTable>
        </div>
      )}
    </ReportFrame>
  );
}
