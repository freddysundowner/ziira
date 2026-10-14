import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api, Combobox, DataTable, Field, formatDate, humanise, money, Pager, unwrap, useQuery, useTranslation } from "@/sdk";

import { accountOptions, useAccounts } from "../api";
import { ReportFrame } from "../components/ReportFrame";
import type { ReportProps } from "./types";

const PAGE = 100;

/** The general ledger of one account: opening balance, each line with a running balance, closing balance. */
export function LedgerReport({ scope, from, to }: ReportProps) {
  const { t } = useTranslation("finance");
  const [params] = useSearchParams();
  const [accountId, setAccountId] = useState(params.get("account") ?? "");
  const [pageState, setPageState] = useState({ key: "", page: 0 });
  const accounts = useAccounts(scope.companyId, true);
  const key = `${scope.companyId}|${scope.branchId}|${accountId}|${from}|${to}`;
  const page = pageState.key === key ? pageState.page : 0;
  const report = useQuery({
    enabled: !!scope.companyId && !!accountId, queryKey: ["finance", "ledger", key, page],
    queryFn: () => unwrap(api.GET("/api/v1/finance/reports/general-ledger", { params: { query: {
      company_id: scope.companyId, account_id: accountId, date_from: from, date_to: to, branch_id: scope.branchId || undefined, limit: PAGE + 1, offset: page * PAGE } } })),
  });
  const r = report.data;
  const c = scope.currency;
  return (
    <ReportFrame title={t("reports.ledger")} company={scope.company?.name ?? ""} period={`${r ? `${r.code} ${r.name} · ` : ""}${formatDate(from)} – ${formatDate(to)}`}
      loading={!!accountId && report.isLoading} error={report.error?.message} onRetry={() => void report.refetch()}
      actions={<div className="w-72"><Field label={t("account")}><Combobox value={accountId} onChange={setAccountId} options={accountOptions(accounts.data)} placeholder={t("chooseAccount")} /></Field></div>}>
      {!accountId ? <p className="py-8 text-center text-sm text-muted">{t("chooseAccountHint")}</p> : r && (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-6 text-sm">
            <span>{t("openingBalance")}: <b className="tnum">{money(r.opening, c)}</b></span>
            <span>{t("closingBalance")}: <b className="tnum">{money(r.closing, c)}</b></span>
          </div>
          <DataTable dense rows={r.lines.slice(0, PAGE)} rowKey={(l) => `${l.entry_id}-${l.debit}-${l.credit}-${l.description}`} empty={{ title: t("nothingPosted") }}
            columns={[
              { header: t("date"), cell: (l) => formatDate(l.entry_date) },
              { header: t("number"), cell: (l) => <Link className="font-mono text-xs hover:underline" to={`/finance/journal/${l.entry_id}`}>{l.number}</Link> },
              { header: t("description"), hideBelow: "md", cell: (l) => l.description ?? humanise(l.source_type) },
              { header: t("debit"), align: "right", cell: (l) => (Number(l.debit) ? money(l.debit, c) : "") },
              { header: t("credit"), align: "right", cell: (l) => (Number(l.credit) ? money(l.credit, c) : "") },
              { header: t("balance"), align: "right", cell: (l) => money(l.balance, c) },
            ]}
            footer={<Pager page={page} onPage={(p) => setPageState({ key, page: p })} hasNext={r.lines.length > PAGE} count={Math.min(r.lines.length, PAGE)} />} />
        </div>
      )}
    </ReportFrame>
  );
}
