import { useState } from "react";
import { Link } from "react-router-dom";

import { api, Alert, Badge, Checkbox, DataTable, formatDate, humanise, money, unwrap, useQuery, useTranslation } from "@/sdk";

import { ReportFrame } from "../components/ReportFrame";
import type { ReportProps } from "./types";

export function TrialBalanceReport({ scope, from, to }: ReportProps) {
  const { t } = useTranslation("finance");
  const [zero, setZero] = useState(false);
  const query = { company_id: scope.companyId, as_of: to, branch_id: scope.branchId || undefined, include_zero: zero };
  const report = useQuery({
    enabled: !!scope.companyId, queryKey: ["finance", "trial-balance", query],
    queryFn: () => unwrap(api.GET("/api/v1/finance/reports/trial-balance", { params: { query } })),
  });
  const r = report.data;
  const c = scope.currency;
  return (
    <ReportFrame title={t("reports.trial")} company={scope.company?.name ?? ""} period={t("asOf", { date: formatDate(to) })}
      loading={report.isLoading} error={report.error?.message} onRetry={() => void report.refetch()}
      actions={<Checkbox label={t("showZero")} checked={zero} onChange={(e) => setZero(e.target.checked)} />}>
      {r && (
        <div className="space-y-3">
          {r.balanced ? <Badge tone="ok">{t("balancedBooks")}</Badge> : <Alert tone="bad">{t("notBalanced")}</Alert>}
          <DataTable dense rows={r.lines} rowKey={(l) => l.account_id} empty={{ title: t("nothingPosted"), hint: t("nothingPostedHint") }}
            columns={[
              { header: t("code"), cell: (l) => <span className="font-mono text-xs">{l.code}</span> },
              { header: t("account"), cell: (l) => (
                <Link className="font-medium hover:underline" to={`/finance/reports/ledger?account=${l.account_id}&from=${from}&to=${to}`}>{l.name}</Link>) },
              { header: t("type"), hideBelow: "md", cell: (l) => <Badge>{t(`accountTypes.${l.type}`, humanise(l.type))}</Badge> },
              { header: t("debit"), align: "right", cell: (l) => money(l.debit, c) },
              { header: t("credit"), align: "right", cell: (l) => money(l.credit, c) },
              { header: t("balance"), hideBelow: "sm", align: "right", cell: (l) => money(l.balance, c) },
            ]}
            footer={r.lines.length > 0 && (
              <div className="tnum flex flex-wrap justify-end gap-x-6 gap-y-1 border-t border-line px-4 py-2.5 text-sm font-semibold">
                <span>{t("totals")}</span><span>{money(r.total_debit, c)}</span><span>{money(r.total_credit, c)}</span>
              </div>)} />
        </div>
      )}
    </ReportFrame>
  );
}
