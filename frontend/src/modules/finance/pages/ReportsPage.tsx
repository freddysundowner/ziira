import { Link, useNavigate, useParams } from "react-router-dom";

import { EmptyState, Input, PageHeader, Select, Tabs, today, monthStart, useTranslation } from "@/sdk";
import { useState } from "react";

import { ScopeSelects, useScope } from "../scope";
import { BalanceSheetReport } from "../reports/BalanceSheetReport";
import { CashFlowReport } from "../reports/CashFlowReport";
import { JournalExport } from "../reports/JournalExport";
import { LedgerReport } from "../reports/LedgerReport";
import { ProfitLossReport } from "../reports/ProfitLossReport";
import { TrialBalanceReport } from "../reports/TrialBalanceReport";
import type { ReportProps } from "../reports/types";
import { VatReport } from "../reports/VatReport";

const REPORTS = {
  pnl: { view: ProfitLossReport, asOf: false },
  balance: { view: BalanceSheetReport, asOf: true },
  cashflow: { view: CashFlowReport, asOf: false },
  vat: { view: VatReport, asOf: false },
  trial: { view: TrialBalanceReport, asOf: true },
  ledger: { view: LedgerReport, asOf: false },
  export: { view: JournalExport, asOf: false },
} as const;
type ReportId = keyof typeof REPORTS;
const IDS = Object.keys(REPORTS) as ReportId[];

/** All financial reports behind one set of filters (company, branch, dates) and tabs. The tab is in the address so a report can be bookmarked. */
export default function ReportsPage() {
  const { t } = useTranslation("finance");
  const { report: param } = useParams();
  const navigate = useNavigate();
  const scope = useScope();
  const [from, setFrom] = useState(monthStart());
  const [to, setTo] = useState(today());
  const known = IDS.find((id) => id === param);
  const active: ReportId = known ?? "pnl";
  const { view: View, asOf } = REPORTS[active];
  const props: ReportProps = { scope, from, to };
  const bad = !asOf && from > to;

  if (param && !known) {
    return (
      <>
        <PageHeader title={t("reports.title")} description={t("reports.hint")} />
        <EmptyState title={t("reports.notFound")} hint={t("reports.notFoundHint")} action={<Link className="font-medium text-brand-strong underline" to="/finance/reports">{t("reports.allReports")}</Link>} />
      </>
    );
  }

  return (
    <>
      <PageHeader title={t("reports.title")} description={t("reports.hint")} />
      <Tabs value={active} onChange={(id) => navigate(`/finance/reports/${id}`)} tabs={IDS.map((id) => ({ id, label: t(`reports.${id}`) }))} />
      <div className="no-print mb-4 flex flex-wrap items-center gap-2">
        <ScopeSelects scope={scope} />
        {!asOf && <Input type="date" aria-label={t("from")} className="w-auto" value={from} max={to} onChange={(e) => setFrom(e.target.value)} />}
        {!asOf && <span className="text-muted">–</span>}
        <Input type="date" aria-label={asOf ? t("asOfLabel") : t("to")} className="w-auto" value={to} onChange={(e) => setTo(e.target.value)} />
        <Select aria-label={t("quickRange")} className="w-auto" value="" onChange={(e) => {
          const v = e.target.value;
          const d = new Date();
          if (v === "month") { setFrom(monthStart()); setTo(today()); }
          if (v === "year") { setFrom(`${d.getFullYear()}-01-01`); setTo(today()); }
          if (v === "lastMonth") {
            const first = new Date(d.getFullYear(), d.getMonth() - 1, 1);
            const last = new Date(d.getFullYear(), d.getMonth(), 0);
            const iso = (x: Date) => new Date(x.getTime() - x.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
            setFrom(iso(first)); setTo(iso(last));
          }
        }}>
          <option value="">{t("quickRange")}</option>
          <option value="month">{t("thisMonth")}</option>
          <option value="lastMonth">{t("lastMonth")}</option>
          <option value="year">{t("thisYear")}</option>
        </Select>
      </div>
      {bad ? <p className="text-sm text-bad">{t("dateOrder")}</p> : <View {...props} />}
    </>
  );
}
