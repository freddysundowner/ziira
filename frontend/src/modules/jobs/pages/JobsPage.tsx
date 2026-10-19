import { LayoutGrid, List, Plus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Button, PageHeader, readStored, Skeleton, useCan, useDebounced, useTranslation, writeStored } from "@/sdk";

import { JobBoard } from "../components/JobBoard";
import { JobFilters, NO_FILTERS } from "../components/JobFilters";
import { JobList } from "../components/JobList";
import { PackStepsBanner } from "../components/PackStepsBanner";
import { useJobsCompany } from "../hooks";

type View = "board" | "list";
const VIEW_KEY = "ziira.jobs.view";

/** All the jobs, as a board of stages or as a list. The choice is remembered. */
export default function JobsPage() {
  const { t } = useTranslation("jobs");
  const { companyId, branches, isLoading } = useJobsCompany();
  const canManage = useCan("jobs.manage");
  const [view, setView] = useState<View>(() => (readStored(VIEW_KEY) === "list" ? "list" : "board"));
  const [filters, setFilters] = useState(NO_FILTERS);
  const search = useDebounced(filters.search.trim());
  const choose = (v: View) => { setView(v); writeStored(VIEW_KEY, v); };

  return (
    <>
      <PageHeader title={t("menu.jobs")} description={t("jobs.hint")}
        actions={<>
          <div role="group" aria-label={t("jobs.view")} className="inline-flex rounded-lg border border-line bg-surface p-0.5 shadow-card">
            {([["board", LayoutGrid], ["list", List]] as const).map(([id, Icon]) => (
              <button key={id} type="button" aria-pressed={view === id} onClick={() => choose(id)}
                className={`inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium ${view === id ? "bg-brand text-brand-ink" : "text-muted hover:text-ink"}`}>
                <Icon className="h-3.5 w-3.5" />{t(`jobs.${id}`)}
              </button>
            ))}
          </div>
          {canManage && <Link to="/jobs/new"><Button><Plus className="h-4 w-4" />{t("menu.receive")}</Button></Link>}
        </>} />
      {companyId && <PackStepsBanner companyId={companyId} />}
      <JobFilters value={filters} onChange={setFilters} branches={branches} />
      {isLoading || !companyId ? <Skeleton className="h-64" /> : view === "board"
        ? <JobBoard companyId={companyId} filters={filters} search={search} />
        : <JobList companyId={companyId} filters={filters} search={search} />}
    </>
  );
}
