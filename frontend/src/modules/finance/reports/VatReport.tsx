import { api, DataTable, formatDate, humanise, money, Stat, type Schemas, useQuery, useTranslation } from "@/sdk";

import { json } from "../api";
import { CsvButton } from "../components/CsvButton";
import { ReportFrame } from "../components/ReportFrame";
import type { ReportProps } from "./types";

export function VatReport({ scope, from, to }: ReportProps) {
  const { t } = useTranslation("finance");
  const query = { company_id: scope.companyId, date_from: from, date_to: to, branch_id: scope.branchId || undefined };
  const report = useQuery({
    enabled: !!scope.companyId, queryKey: ["finance", "vat", query],
    queryFn: () => json<Schemas["VatReportOut"]>(api.GET("/api/v1/finance/reports/vat-summary", { params: { query } })),
  });
  const v = report.data;
  const c = scope.currency;
  const sources = (rows: { label: string; amount: string }[]) => (
    <DataTable dense rows={rows} rowKey={(r) => r.label} empty={{ title: t("nothingPosted") }}
      columns={[{ header: t("source"), cell: (r) => humanise(r.label) }, { header: t("amount"), align: "right", cell: (r) => money(r.amount, c) }]} />
  );
  return (
    <ReportFrame title={t("reports.vat")} company={scope.company?.name ?? ""} period={`${formatDate(from)} – ${formatDate(to)}`}
      loading={report.isLoading} error={report.error?.message} onRetry={() => void report.refetch()}
      actions={<CsvButton fallbackName="vat-summary.csv" request={() => api.GET("/api/v1/finance/reports/vat-summary", { params: { query: { ...query, format: "csv" } }, parseAs: "blob" })} />}>
      {v && (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label={t("salesNet")} value={money(v.sales_net, c)} />
            <Stat label={t("outputVat")} value={money(v.output_vat, c)} hint={t("outputVatHint")} />
            <Stat label={t("inputVat")} value={money(v.input_vat, c)} hint={t("inputVatHint")} />
            <Stat label={t("netPayable")} value={money(v.net_payable, c)} tone={Number(v.net_payable) > 0 ? "bad" : "ok"} hint={t("netPayableHint")} />
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div><h3 className="mb-2 text-sm font-semibold">{t("outputBySource")}</h3>{sources(v.output_by_source)}</div>
            <div><h3 className="mb-2 text-sm font-semibold">{t("inputBySource")}</h3>{sources(v.input_by_source)}</div>
          </div>
        </div>
      )}
    </ReportFrame>
  );
}
