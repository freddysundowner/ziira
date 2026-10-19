import { api, Badge, DataTable, formatDate, Pager, unwrap, usePagedList, useTranslation } from "@/sdk";
import { Link } from "react-router-dom";

import { jobHref } from "../public";
import type { Filters } from "./JobFilters";
import { StageBadge } from "./StageBadge";

/** The same jobs as a table, paged by the server. */
export function JobList({ companyId, filters, search }: { companyId: string; filters: Filters; search: string }) {
  const { t } = useTranslation("jobs");
  const list = usePagedList(["jobs", "list", companyId, filters.branchId, filters.assigneeId, filters.late, filters.showClosed, filters.waitingOn, search],
    (limit, offset) => unwrap(api.GET("/api/v1/jobs/jobs", { params: { query: {
      company_id: companyId, branch_id: filters.branchId || undefined, assignee_id: filters.assigneeId || undefined, overdue: filters.late, waiting_on: (filters.waitingOn || undefined) as "parts" | "approval" | "insurer" | undefined,
      open_only: !filters.showClosed, search: search || undefined, limit, offset } } })), 25, !!companyId);
  return (
    <DataTable rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()}
      rowKey={(j) => j.id} rowHref={(j) => jobHref(j.id)}
      empty={{ title: t("list.empty"), hint: t("list.emptyHint") }}
      footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      columns={[
        { header: t("list.number"), cell: (j) => <Link to={jobHref(j.id)} className="tnum font-medium text-brand-strong hover:underline">{j.number}</Link> },
        { header: t("list.job"), cell: (j) => (
          <div className="min-w-0"><p className="truncate font-medium">{j.title}</p><p className="truncate text-xs text-muted">{[j.asset?.label, j.customer_name].filter(Boolean).join(" · ")}</p></div>
        ) },
        { header: t("list.stage"), cell: (j) => <span className="inline-flex flex-wrap gap-1"><StageBadge stage={j.status} />{j.is_rework && <Badge tone="warn">{t("card.returnVisit")}</Badge>}{j.waiting_on.map((w) => <Badge key={w} tone="warn">{t(`garage.waiting.${w}`)}</Badge>)}</span> },
        { header: t("list.assignee"), cell: (j) => j.assignee_name ?? "—", hideBelow: "md" },
        { header: t("list.promised"), cell: (j) => <span className={j.overdue ? "font-medium text-bad" : undefined}>{formatDate(j.promised_at)}</span>, hideBelow: "sm" },
        { header: t("list.received"), cell: (j) => formatDate(j.received_at), hideBelow: "lg" },
      ]} />
  );
}
