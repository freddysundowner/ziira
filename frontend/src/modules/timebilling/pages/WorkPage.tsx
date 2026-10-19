import { useState } from "react";

import { api, EmptyState, ErrorState, PageHeader, Select, Skeleton, Tabs, unwrap, useQuery, useSession, useTranslation } from "@/sdk";

import { CompanyPicker } from "../components/CompanyBar";
import { TaskCard } from "../components/TaskCard";
import { useWorkCompany } from "../hooks";

/** Every dated piece of client work: what is late, what is coming, and who is doing it. */
export default function WorkPage() {
  const { t } = useTranslation("timebilling");
  const { companyId, companies, setCompanyId } = useWorkCompany();
  const session = useSession();
  const [status, setStatus] = useState<"open" | "done">("open");
  const [mine, setMine] = useState("all");
  const list = useQuery({
    queryKey: ["timebilling", "tasks", "all", companyId, status, mine], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/tasks", { params: { query: { company_id: companyId, status, assignee_id: mine === "mine" ? session.me?.user_id ?? undefined : undefined, limit: 200 } } })),
  });
  return (
    <>
      <PageHeader title={t("work.title")} description={t("work.hint")} actions={<CompanyPicker companies={companies} value={companyId} onChange={setCompanyId} />} />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Tabs tabs={[{ id: "open", label: t("work.tabOpen") }, { id: "done", label: t("work.tabDone") }]} value={status} onChange={setStatus} />
        <Select className="w-44" aria-label={t("work.whose")} value={mine} onChange={(e) => setMine(e.target.value)}><option value="all">{t("work.everyone")}</option><option value="mine">{t("work.mine")}</option></Select>
      </div>
      {list.isLoading && <Skeleton className="h-40 w-full" />}
      {list.error && <ErrorState message={list.error.message} onRetry={() => void list.refetch()} />}
      {list.data && list.data.length === 0 && <EmptyState title={t("work.none")} hint={t("work.noneHint")} />}
      <div className="grid gap-3 lg:grid-cols-2">{list.data?.map((x) => <TaskCard key={x.id} task={x} showProject />)}</div>
    </>
  );
}
