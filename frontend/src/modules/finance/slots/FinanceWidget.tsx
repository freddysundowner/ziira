import { Link } from "react-router-dom";

import { api, ErrorState, Figure, StatRow, monthStart, money, Skeleton, today, type Schemas, useCompany, useQuery, useTranslation } from "@/sdk";
import { json } from "../api";

/** Home page box: cash and bank position, and profit so far this month, from the books. */
export default function FinanceWidget() {
  const { t } = useTranslation("finance");
  const { company } = useCompany();
  const companyId = company?.id ?? "";
  const range = { company_id: companyId, date_from: monthStart(), date_to: today() };
  const cash = useQuery({ enabled: !!companyId, queryKey: ["finance", "widget-cash", range], queryFn: () => json<Schemas["CashFlowOut"]>(api.GET("/api/v1/finance/reports/cash-flow", { params: { query: range } })) });
  const profit = useQuery({ enabled: !!companyId, queryKey: ["finance", "widget-profit", range], queryFn: () => json<Schemas["ProfitReportOut"]>(api.GET("/api/v1/finance/reports/profit-and-loss", { params: { query: range } })) });

  const error = cash.error ?? profit.error;
  if (error) return <ErrorState message={error.message} onRetry={() => { void cash.refetch(); void profit.refetch(); }} />;
  if (!company || cash.isLoading || profit.isLoading) return <Skeleton className="h-16 w-full" />;
  const net = profit.data?.consolidated.net_profit;
  return (
    <StatRow>
      <Link to="/finance/reports/cashflow" className="block min-w-0"><Figure label={t("widget.cash")} value={money(cash.data?.closing, company.currency)} /></Link>
      <Link to="/finance/reports/pnl" className="block min-w-0"><Figure label={t("widget.profit")} value={money(net, company.currency)} tone={Number(net) < 0 ? "bad" : "ok"} /></Link>
    </StatRow>
  );
}
