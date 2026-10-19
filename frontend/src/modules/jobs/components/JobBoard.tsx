import { useMemo, useState } from "react";

import { api, cx, EmptyState, ErrorState, Skeleton, unwrap, useQuery, useTranslation } from "@/sdk";

import { useWorkflow } from "../hooks";
import { canMove, groupByStage } from "../lib";
import type { JobSummary, StageRef } from "../types";
import type { Filters } from "./JobFilters";
import { JobCard } from "./JobCard";
import { useStageMover } from "./StageMover";

/** The job board: a column for each stage, the live jobs as cards. */
export function JobBoard({ companyId, filters, search }: { companyId: string; filters: Filters; search: string }) {
  const { t } = useTranslation("jobs");
  const workflow = useWorkflow(companyId);
  const mover = useStageMover();
  const [dragging, setDragging] = useState<JobSummary | null>(null);
  const [over, setOver] = useState("");
  const board = useQuery({
    queryKey: ["jobs", "board", companyId, filters.branchId, filters.assigneeId, filters.late, filters.showClosed, search], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/jobs/jobs/board", { params: { query: {
      company_id: companyId, branch_id: filters.branchId || undefined, assignee_id: filters.assigneeId || undefined,
      overdue: filters.late, include_closed: filters.showClosed, search: search || undefined } } })),
  });
  const columns = useMemo(() => groupByStage((board.data?.statuses ?? []).filter((s) => filters.showClosed || s.kind !== "closed"),
    (board.data?.jobs ?? []).filter((j) => !filters.waitingOn || j.waiting_on.includes(filters.waitingOn))), [board.data, filters.showClosed, filters.waitingOn]);

  if (board.error || workflow.error) return <ErrorState title={t("board.loadFailed")} message={(board.error ?? workflow.error)?.message} onRetry={() => { void board.refetch(); void workflow.refetch(); }} />;
  if (!board.data || !workflow.data) return <div className="flex gap-3 overflow-hidden">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-64 w-72 shrink-0" />)}</div>;
  if (board.data.jobs.length === 0 && !search && !filters.late && !filters.assigneeId) {
    return <EmptyState title={t("board.empty")} hint={t("board.emptyHint")} />;
  }

  const accepts = (stage: StageRef) => !!dragging && canMove(workflow.data, dragging.status.id, stage.id);
  const drop = (stage: StageRef) => { const job = dragging; setDragging(null); setOver(""); if (job && canMove(workflow.data, job.status.id, stage.id)) mover.move(job, stage); };

  return (
    <>
      {board.data.truncated && <p className="mb-3 rounded-lg bg-warn-soft px-3 py-2 text-sm text-warn">{t("board.truncated")}</p>}
      <div className="-mx-4 flex snap-x snap-mandatory gap-3 overflow-x-auto px-4 pb-4 sm:mx-0 sm:px-0">
        {columns.map(({ stage, jobs }) => {
          const ok = accepts(stage);
          return (
            <section key={stage.id} aria-label={stage.name}
              onDragOver={(e) => { if (ok) { e.preventDefault(); e.dataTransfer.dropEffect = "move"; setOver(stage.id); } }}
              onDragLeave={() => setOver((o) => (o === stage.id ? "" : o))} onDrop={(e) => { e.preventDefault(); drop(stage); }}
              className={cx("w-[85vw] shrink-0 snap-start rounded-xl border bg-sunken/60 p-2 transition-colors sm:w-72",
                ok ? (over === stage.id ? "border-brand bg-brand-soft" : "border-brand/60 border-dashed") : "border-line", dragging && !ok && "opacity-50")}>
              <header className="flex items-center justify-between px-1 pb-2 pt-1">
                <h3 className="text-sm font-semibold">{stage.name}</h3>
                <span className="tnum rounded-full bg-surface px-2 text-xs text-muted">{jobs.length}</span>
              </header>
              <div className="space-y-2">
                {jobs.map((job) => <JobCard key={job.id} job={job} workflow={workflow.data} onMove={mover.move} onDragStart={setDragging} onDragEnd={() => { setDragging(null); setOver(""); }} />)}
                {jobs.length === 0 && <p className="px-2 py-6 text-center text-xs text-muted">{ok ? t("board.dropHere") : t("board.noneHere")}</p>}
              </div>
            </section>
          );
        })}
      </div>
      {mover.dialog}
    </>
  );
}
