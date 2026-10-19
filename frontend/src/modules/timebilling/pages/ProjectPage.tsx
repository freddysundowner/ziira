import { Pencil } from "lucide-react";
import { useState } from "react";
import { useParams } from "react-router-dom";

import { api, Badge, Button, ErrorState, PageHeader, Skeleton, Tabs, unwrap, useCan, useCurrency, useQuery, useTranslation } from "@/sdk";

import { MilestonesTab } from "../components/MilestonesTab";
import { ProjectForm } from "../components/ProjectForm";
import { ProjectOverview } from "../components/ProjectOverview";
import { ProjectTime } from "../components/ProjectTime";
import { WorkTab } from "../components/WorkTab";
import { RetainerTab } from "../components/RetainerTab";
import type { Project } from "../types";

type TabId = "overview" | "time" | "work" | "milestones" | "retainer";

/** One project: how it stands, its time, and (by billing mode) its milestones or retainer. */
export default function ProjectPage() {
  const { t } = useTranslation("timebilling");
  const { projectId = "" } = useParams();
  const canManage = useCan("projects.manage");
  const [tab, setTab] = useState<TabId>("overview");
  const [editing, setEditing] = useState(false);
  const project = useQuery<Project>({
    queryKey: ["timebilling", "project", projectId],
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/projects/{project_id}", { params: { path: { project_id: projectId } } })),
  });
  const currency = useCurrency(project.data?.company_id);

  if (project.isLoading) return <Skeleton className="h-64 w-full" />;
  if (project.error || !project.data) return <ErrorState message={project.error?.message} onRetry={() => void project.refetch()} />;
  const p = project.data;
  const tabs: { id: TabId; label: string }[] = [
    { id: "overview", label: t("project.tabs.overview") },
    { id: "time", label: t("project.tabs.time") },
    { id: "work", label: t("project.tabs.work") },
    ...(p.billing_mode === "fixed_fee" ? [{ id: "milestones" as const, label: t("project.tabs.milestones") }] : []),
    ...(p.billing_mode === "retainer" ? [{ id: "retainer" as const, label: t("project.tabs.retainer") }] : []),
  ];
  const shown = tabs.some((x) => x.id === tab) ? tab : "overview";

  return (
    <>
      <PageHeader back={{ to: "/projects", label: t("projects.title") }} title={`${p.code} · ${p.name}`}
        description={<span className="inline-flex flex-wrap items-center gap-2">{p.client_name}<Badge>{t(`projects.mode.${p.billing_mode}`)}</Badge><Badge tone={p.status === "active" ? "ok" : "neutral"}>{t(`projects.state.${p.status}`)}</Badge></span>}
        actions={canManage && <Button variant="secondary" onClick={() => setEditing(true)}><Pencil className="h-4 w-4" />{t("edit")}</Button>} />
      <Tabs tabs={tabs} value={shown} onChange={setTab} />
      {shown === "overview" && <ProjectOverview project={p} currency={currency} />}
      {shown === "time" && <ProjectTime project={p} />}
      {shown === "work" && <WorkTab project={p} />}
      {shown === "milestones" && <MilestonesTab project={p} currency={currency} />}
      {shown === "retainer" && <RetainerTab project={p} currency={currency} />}
      <ProjectForm open={editing} onClose={() => setEditing(false)} companyId={p.company_id} branches={[]} project={p} />
    </>
  );
}
