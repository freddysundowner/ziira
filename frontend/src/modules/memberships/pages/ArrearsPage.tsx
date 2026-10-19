import { Repeat, Wallet } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api, Badge, DataTable, formatDate, money, PageHeader, Pager, Select, Stat, unwrap, useCompany, useCurrency, usePagedList, useTranslation } from "@/sdk";

import { DownloadButton } from "../download";
import { sumDecimals } from "../logic";
import { personPath, recurringPath } from "../public";

const AGES = [1, 8, 31, 61] as const;

/** Who owes money, oldest first: call or message them, take a payment, or download the list. */
export default function ArrearsPage() {
  const { t } = useTranslation("memberships");
  const { company } = useCompany();
  const currency = useCurrency(company?.id);
  const [minDays, setMinDays] = useState<number>(1);
  const list = usePagedList(["memberships", "arrears", company?.id, minDays], (limit, offset) =>
    unwrap(api.GET("/api/v1/memberships/arrears", { params: { query: { company_id: company?.id ?? "", min_days: minDays, limit, offset } } })), 50, !!company);
  const total = sumDecimals((list.rows ?? []).map((r) => r.owed));

  return (
    <>
      <PageHeader title={t("arrearsMenu")} description={t("arrears.hint")}
        actions={(
          <>
            <Link to={recurringPath} className="inline-flex h-10 items-center gap-2 rounded-lg border border-line bg-surface px-4 text-sm font-semibold shadow-card hover:bg-sunken"><Repeat className="h-4 w-4" />{t("recurringMenu")}</Link>
            {company && <DownloadButton fileName="arrears.csv" request={() => api.GET("/api/v1/memberships/exports/{kind}", { params: { path: { kind: "arrears" }, query: { company_id: company.id } }, parseAs: "blob" })}>{t("arrears.download")}</DownloadButton>}
          </>
        )} />
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-3">
        <Stat label={t("arrears.owedNow")} value={money(total, currency)} loading={list.query.isLoading} tone={Number(total) > 0 ? "bad" : undefined} hint={t("arrears.onThisPage")} />
        <Stat label={t("arrears.people")} value={list.rows?.length ?? 0} loading={list.query.isLoading} hint={list.hasNext ? t("arrears.more") : undefined} />
      </div>
      <DataTable
        rows={list.rows} loading={list.query.isLoading || !company} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(r) => r.customer_id}
        rowHref={(r) => `${personPath(r.customer_id)}?tab=money`}
        toolbar={(
          <Select className="w-52" aria-label={t("arrears.age")} value={String(minDays)} onChange={(e) => setMinDays(Number(e.target.value))}>
            {AGES.map((d) => <option key={d} value={d}>{t(`arrears.ages.${d}`)}</option>)}
          </Select>
        )}
        empty={{ title: minDays > 1 ? t("arrears.noneThatOld") : t("arrears.none"), hint: minDays > 1 ? undefined : t("arrears.noneHint") }}
        columns={[
          { header: t("customer"), sortValue: (r) => r.customer_name ?? "", cell: (r) => <span><span className="font-medium">{r.customer_name ?? "—"}</span><span className="block text-xs text-muted">{r.phone ?? r.email ?? ""}</span></span> },
          { header: t("arrears.owed"), align: "right", sortValue: (r) => Number(r.owed), cell: (r) => <span className="font-semibold text-bad">{money(r.owed, currency)}</span> },
          { header: t("arrears.oldest"), hideBelow: "sm", sortValue: (r) => r.oldest_due, cell: (r) => formatDate(r.oldest_due) },
          { header: t("arrears.daysLate"), align: "right", sortValue: (r) => r.days_late, cell: (r) => <Badge tone={r.days_late > 30 ? "bad" : "warn"}>{t("arrears.days", { count: r.days_late })}</Badge> },
          { header: t("arrears.invoices"), hideBelow: "md", cell: (r) => r.invoice_numbers.join(", ") || r.invoices },
          { header: t("arrears.lastReminder"), hideBelow: "lg", cell: (r) => (r.last_reminder ? formatDate(r.last_reminder) : t("arrears.never")) },
          { header: t("tabs.members"), hideBelow: "lg", cell: (r) => r.members.map((m) => `${m.number} ${m.plan_name}`).join(", ") },
          { header: "", align: "right", cell: (r) => <Link to={`${personPath(r.customer_id)}?tab=money`} className="inline-flex min-h-9 items-center gap-1 rounded-lg border border-line px-3 text-sm font-medium hover:bg-sunken"><Wallet className="h-4 w-4" />{t("pay.take")}</Link> },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />} />
    </>
  );
}
