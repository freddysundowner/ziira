import { Plus } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api, Badge, Button, DataTable, Input, PageHeader, Pager, Select, StatusBadge, unwrap, useCan, useDebounced, usePagedList, useTranslation } from "@/sdk";

import { CompanyPicker } from "../components/CompanyBar";
import { ProjectForm } from "../components/ProjectForm";
import { useWorkCompany } from "../hooks";
import { formatDuration } from "../lib";
import { PROJECT_STATES } from "../types";

/** Projects: search, filter by status, add a project. */
export default function ProjectsPage() {
  const { t } = useTranslation("timebilling");
  const navigate = useNavigate();
  const canManage = useCan("projects.manage");
  const { company, companyId, companies, setCompanyId } = useWorkCompany();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("active");
  const [creating, setCreating] = useState(false);
  const q = useDebounced(search.trim());
  const list = usePagedList(["timebilling", "projects", companyId, q, status], (limit, offset) =>
    unwrap(api.GET("/api/v1/timebilling/projects", { params: { query: { company_id: companyId, search: q || undefined, status: status || undefined, limit, offset } } })), 25, !!companyId);
  const add = canManage && <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" />{t("projects.new")}</Button>;

  return (
    <>
      <PageHeader title={t("projects.title")} description={t("projects.hint")} actions={<><CompanyPicker companies={companies} value={companyId} onChange={setCompanyId} />{add}</>} />
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(p) => p.id}
        rowHref={(p) => `/projects/${p.id}`}
        toolbar={<>
          <Input className="max-w-sm" aria-label={t("projects.search")} placeholder={t("projects.search")} value={search} onChange={(e) => setSearch(e.target.value)} />
          <Select className="w-44" aria-label={t("status")} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("projects.allStatuses")}</option>
            {PROJECT_STATES.map((s) => <option key={s} value={s}>{t(`projects.state.${s}`)}</option>)}
          </Select>
        </>}
        empty={{ title: q || status ? t("projects.noMatch") : t("projects.empty"), hint: q || status ? undefined : t("projects.emptyHint"), action: !q && !status ? add || undefined : undefined }}
        columns={[
          { header: t("projects.code"), sortValue: (p) => p.code, cell: (p) => <span className="font-mono text-xs font-medium">{p.code}</span> },
          { header: t("projects.name"), sortValue: (p) => p.name, cell: (p) => <span className="font-medium">{p.name}</span> },
          { header: t("client"), hideBelow: "sm", sortValue: (p) => p.client_name, cell: (p) => p.client_name },
          { header: t("projects.billingMode"), hideBelow: "md", cell: (p) => <Badge>{t(`projects.mode.${p.billing_mode}`)}</Badge> },
          { header: t("projects.budgetHours"), hideBelow: "lg", align: "right", cell: (p) => (p.budget_minutes ? <span className="tnum">{formatDuration(p.budget_minutes)}</span> : "—") },
          { header: t("status"), cell: (p) => (p.status === "active" ? <StatusBadge status="active" /> : <Badge>{t(`projects.state.${p.status}`)}</Badge>) },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />} />
      <ProjectForm open={creating} onClose={() => setCreating(false)} companyId={companyId} branches={company?.branches ?? []} onSaved={(p) => navigate(`/projects/${p.id}`)} />
    </>
  );
}
