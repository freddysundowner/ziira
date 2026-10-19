import { GripVertical, ListChecks, MoreVertical, Package, User } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge, cx, formatDate, Menu, useCan, useTranslation } from "@/sdk";

import { jobHref } from "../public";
import type { JobSummary, Stage, StageRef } from "../types";
import { nextStages } from "../lib";

/** One job on the board. Drag it to a column the workflow allows, or use "Move to..." (phones cannot drag). */
export function JobCard({ job, workflow, onMove, onDragStart, onDragEnd }: {
  job: JobSummary; workflow: readonly Stage[]; onMove: (job: JobSummary, to: StageRef) => void;
  onDragStart: (job: JobSummary) => void; onDragEnd: () => void;
}) {
  const { t } = useTranslation("jobs");
  const canManage = useCan("jobs.manage");
  const targets = nextStages(workflow, workflow.find((s) => s.id === job.status.id)?.moves_to ?? []);
  const draggable = canManage && !job.locked && targets.length > 0;
  return (
    <article draggable={draggable} aria-label={`${job.number} ${job.title}`}
      onDragStart={(e) => { e.dataTransfer.setData("text/plain", job.id); e.dataTransfer.effectAllowed = "move"; onDragStart(job); }} onDragEnd={onDragEnd}
      className={cx("rounded-lg border bg-surface p-3 shadow-card", job.overdue ? "border-bad/50" : "border-line", draggable && "cursor-grab active:cursor-grabbing")}>
      <div className="flex items-start gap-1">
        {draggable && <GripVertical aria-hidden className="mt-0.5 hidden h-4 w-4 shrink-0 text-muted sm:block" />}
        <div className="min-w-0 flex-1">
          <Link to={jobHref(job.id)} draggable={false} className="block hover:text-brand-strong">
            <span className="tnum text-xs font-medium text-muted">{job.number}</span>
            <span className="block text-sm font-medium leading-snug">{job.title}</span>
          </Link>
        </div>
        {draggable && (
          <Menu label={t("card.moveTo")} items={targets.map((s) => ({ label: s.name, onSelect: () => onMove(job, s) }))}
            trigger={<span className="-mr-1 -mt-1 inline-flex h-9 w-9 items-center justify-center rounded-lg text-muted hover:bg-sunken hover:text-ink"><MoreVertical className="h-4 w-4" /></span>} />
        )}
      </div>
      <div className="mt-2 space-y-1 text-xs text-muted">
        {job.asset && <p className="flex items-center gap-1.5"><Package className="h-3.5 w-3.5 shrink-0" /><span className="truncate">{job.asset.label}</span></p>}
        {(job.customer_name || job.assignee_name) && (
          <p className="flex items-center gap-1.5"><User className="h-3.5 w-3.5 shrink-0" /><span className="truncate">{[job.customer_name, job.assignee_name && t("card.by", { name: job.assignee_name })].filter(Boolean).join(" · ")}</span></p>
        )}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
        {job.promised_at && <span className={cx("tnum", job.overdue ? "font-medium text-bad" : "text-muted")}>{job.overdue ? t("card.late", { date: formatDate(job.promised_at) }) : t("card.due", { date: formatDate(job.promised_at) })}</span>}
        <span className="tnum text-muted">{t("card.days", { n: job.days_in_status })}</span>
        {job.tasks_total > 0 && <span className="tnum inline-flex items-center gap-1 text-muted"><ListChecks className="h-3.5 w-3.5" />{job.tasks_done}/{job.tasks_total}</span>}
        {job.is_rework && <Badge tone="warn">{t("card.returnVisit")}</Badge>}
        {job.waiting_on.map((w) => <Badge key={w} tone="warn">{t(`garage.waiting.${w}`)}</Badge>)}
        {job.has_claim && <Badge tone="info">{t("garage.claim.badge")}</Badge>}
      </div>
    </article>
  );
}
