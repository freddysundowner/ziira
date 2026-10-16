import { Link } from "react-router-dom";

import { api, DataTable, money, Pager, unwrap, usePagedList, useTranslation } from "@/sdk";

import { ageInDays } from "../logic";
import { BAND_SEVERITIES, type GroupedFilters, type View } from "../useGrouped";
import { useNames } from "../useNames";
import { usePlain } from "../usePlain";
import { FindingStatusBadge, SeverityBadge, useAreaLabel } from "./Badges";

/** The same things as a plain list, one row each (for people who like tables, or want to sort and scan). */
export default function FindingsTable({ view, filters, source, filtered }: { view: View; filters: GroupedFilters; source: string; filtered: boolean }) {
  const { t } = useTranslation("intel");
  const areaLabel = useAreaLabel();
  const plain = usePlain();
  const { branchName, currencyOf } = useNames();
  const list = usePagedList(["intel", "findings", view, filters, source], (limit, offset) => unwrap(api.GET("/api/v1/intel/findings", {
    params: { query: {
      view, severity: filters.band ? BAND_SEVERITIES[filters.band] : undefined, area: filters.area || undefined, company_id: filters.companyId || undefined,
      branch_id: filters.branchId || undefined, assigned_to_me: filters.mine || undefined, search: filters.search || undefined,
      source: (source || undefined) as "connected" | "ziira" | undefined, limit, offset } },
  })));
  return (
    <DataTable
      rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(f) => f.id}
      rowHref={(f) => `/intelligence/things/${f.id}`}
      empty={{ title: filtered ? t("noMatch") : t("empty"), hint: filtered ? t("noMatchHint") : t("emptyHint") }}
      columns={[
        { header: t("severity.label"), cell: (f) => <SeverityBadge severity={f.severity} /> },
        { header: t("finding"), cell: (f) => (
          <div className="min-w-0">
            <Link to={`/intelligence/things/${f.id}`} className="font-medium hover:underline">{plain.check(f.check_code)?.title ?? f.summary ?? t("noSummary")}</Link>
            <p className="text-xs text-muted">{f.summary}</p>
            <p className="text-xs text-muted">{areaLabel(f.area)}{branchName(f.branch_id) ? ` · ${branchName(f.branch_id)}` : ""}</p>
          </div>
        ) },
        { header: t("amount"), align: "right", hideBelow: "sm", cell: (f) => (f.amount ? money(f.amount, currencyOf(f.company_id)) : "—") },
        { header: t("status.label"), hideBelow: "sm", cell: (f) => <FindingStatusBadge status={f.status} /> },
        { header: t("age"), align: "right", hideBelow: "md", cell: (f) => t("days", { count: ageInDays(f.first_seen_at) }) },
      ]}
      footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
    />
  );
}
