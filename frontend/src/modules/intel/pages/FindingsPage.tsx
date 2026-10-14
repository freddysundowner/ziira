import { Link } from "react-router-dom";
import { useState } from "react";

import {
  api, Checkbox, DataTable, Input, money, PageHeader, Pager, Select, Stat, unwrap, useCan, useCompany, useDebounced, usePagedList, useQuery, useTranslation,
} from "@/sdk";

import { FindingStatusBadge, SeverityBadge, useAreaLabel } from "../components/Badges";
import { AREAS, ageInDays, SEVERITIES, STATUSES, type StatusFilter, statusesFor } from "../logic";

type Severity = (typeof SEVERITIES)[number];

export default function FindingsPage() {
  const { t } = useTranslation("intel");
  const areaLabel = useAreaLabel();
  const canManage = useCan("findings.manage");
  const canRespond = useCan("findings.respond");
  const { companies } = useCompany();
  const [status, setStatus] = useState<StatusFilter>("open");
  const [severity, setSeverity] = useState("");
  const [area, setArea] = useState("");
  const [companyId, setCompanyId] = useState("");
  const [branchId, setBranchId] = useState("");
  // Someone who can only respond starts on the findings assigned to them.
  const [mine, setMine] = useState(!canManage && canRespond);
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim());

  const summary = useQuery({ queryKey: ["intel", "summary"], queryFn: () => unwrap(api.GET("/api/v1/intel/findings/summary")) });
  const list = usePagedList(["intel", "findings", status, severity, area, companyId, branchId, mine, q], (limit, offset) => unwrap(api.GET("/api/v1/intel/findings", {
    params: { query: {
      status: statusesFor(status), severity: severity ? [severity as Severity] : undefined, area: area || undefined, company_id: companyId || undefined,
      branch_id: branchId || undefined, assigned_to_me: mine || undefined, search: q || undefined, limit, offset } },
  })));

  const branches = (companies.find((c) => c.id === (companyId || (companies.length === 1 ? companies[0].id : "")))?.branches ?? []);
  const branchName = (id: string | null) => companies.flatMap((c) => c.branches).find((b) => b.id === id)?.name;
  const currencyOf = (id: string | null) => companies.find((c) => c.id === id)?.currency ?? companies[0]?.currency;
  const filtered = status !== "open" || !!severity || !!area || !!companyId || !!branchId || mine || !!q;
  const s = summary.data;

  return (
    <>
      <PageHeader title={t("title")} description={t("hint")} />
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <Stat label={t("openFindings")} value={s?.open ?? "—"} loading={summary.isLoading} hint={summary.error?.message} />
        <Stat label={t("atStake")} value={s ? money(s.amount_at_stake, currencyOf(null)) : "—"} loading={summary.isLoading} hint={companies.length > 1 ? t("atStakeMixed") : undefined} />
        <Stat label={t("urgent")} value={s ? (s.by_severity.critical ?? 0) + (s.by_severity.high ?? 0) : "—"} loading={summary.isLoading} tone={s && (s.by_severity.critical ?? 0) + (s.by_severity.high ?? 0) > 0 ? "bad" : undefined} />
      </div>
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(f) => f.id}
        rowHref={(f) => `/findings/${f.id}`}
        toolbar={
          <div className="flex w-full flex-wrap items-center gap-2">
            <Input className="min-w-40 max-w-xs flex-1" aria-label={t("search")} placeholder={t("search")} value={search} onChange={(e) => setSearch(e.target.value)} />
            <Select aria-label={t("statusFilter")} className="w-auto" value={status} onChange={(e) => setStatus(e.target.value as StatusFilter)}>
              <option value="open">{t("filter.open")}</option>
              <option value="closed">{t("filter.closed")}</option>
              <option value="all">{t("filter.all")}</option>
              {STATUSES.map((x) => <option key={x} value={x}>{t(`status.${x}`)}</option>)}
            </Select>
            <Select aria-label={t("severityFilter")} className="w-auto" value={severity} onChange={(e) => setSeverity(e.target.value)}>
              <option value="">{t("allSeverities")}</option>
              {SEVERITIES.map((x) => <option key={x} value={x}>{t(`severity.${x}`)}</option>)}
            </Select>
            <Select aria-label={t("areaFilter")} className="w-auto" value={area} onChange={(e) => setArea(e.target.value)}>
              <option value="">{t("allAreas")}</option>
              {AREAS.map((x) => <option key={x} value={x}>{areaLabel(x)}</option>)}
            </Select>
            {companies.length > 1 && (
              <Select aria-label={t("company")} className="w-auto" value={companyId} onChange={(e) => { setCompanyId(e.target.value); setBranchId(""); }}>
                <option value="">{t("allCompanies")}</option>
                {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </Select>
            )}
            {branches.length > 1 && (
              <Select aria-label={t("branch")} className="w-auto" value={branchId} onChange={(e) => setBranchId(e.target.value)}>
                <option value="">{t("allBranches")}</option>
                {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </Select>
            )}
            {(canRespond || canManage) && <Checkbox label={t("assignedToMe")} checked={mine} onChange={(e) => setMine(e.target.checked)} />}
          </div>
        }
        empty={{ title: filtered ? t("noMatch") : t("empty"), hint: filtered ? t("noMatchHint") : t("emptyHint") }}
        columns={[
          { header: t("severity.label"), cell: (f) => <SeverityBadge severity={f.severity} /> },
          { header: t("finding"), cell: (f) => (
            <div className="min-w-0">
              <Link to={`/findings/${f.id}`} className="font-medium hover:underline">{f.summary ?? t("noSummary")}</Link>
              <p className="text-xs text-muted">{areaLabel(f.area)}{branchName(f.branch_id) ? ` · ${branchName(f.branch_id)}` : ""}</p>
            </div>
          ) },
          { header: t("amount"), align: "right", hideBelow: "sm", cell: (f) => (f.amount ? money(f.amount, currencyOf(f.company_id)) : "—") },
          { header: t("status.label"), hideBelow: "sm", cell: (f) => <FindingStatusBadge status={f.status} /> },
          { header: t("age"), align: "right", hideBelow: "md", cell: (f) => t("days", { count: ageInDays(f.first_seen_at) }) },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
    </>
  );
}
