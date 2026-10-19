import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { api, Button, Card, Checkbox, formatDate, IconButton, Input, unwrap, useTranslation } from "@/sdk";

import { useJobAction } from "../hooks";
import type { Job } from "../types";
import { PersonSelect } from "./pickers";

/** Pieces of work on the job, each with a person and a date. */
export function TasksCard({ job, editable }: { job: Job; editable: boolean }) {
  const { t } = useTranslation("jobs");
  const [title, setTitle] = useState("");
  const [assigneeId, setAssigneeId] = useState("");
  const [due, setDue] = useState("");
  const path = { job_id: job.id };
  const toggle = useJobAction(job.id, (v: { id: string; done: boolean }) => unwrap(api.PATCH("/api/v1/jobs/jobs/{job_id}/tasks/{task_id}", { params: { path: { ...path, task_id: v.id } }, body: { done: v.done } })));
  const remove = useJobAction(job.id, (id: string) => unwrap(api.DELETE("/api/v1/jobs/jobs/{job_id}/tasks/{task_id}", { params: { path: { ...path, task_id: id } } })));
  const add = useJobAction(job.id, () => unwrap(api.POST("/api/v1/jobs/jobs/{job_id}/tasks", { params: { path }, body: { title: title.trim(), assignee_id: assigneeId || null, due_date: due || null } })),
    { onDone: () => { setTitle(""); setAssigneeId(""); setDue(""); } });
  if (job.tasks.length === 0 && !editable) return null;
  return (
    <Card title={t("tasks.title")} description={t("tasks.hint")}>
      {job.tasks.length === 0 && <p className="mb-3 text-sm text-muted">{t("tasks.empty")}</p>}
      <ul className="divide-y divide-line">
        {job.tasks.map((task) => (
          <li key={task.id} className="flex items-center gap-3 py-2">
            <Checkbox label={<span className={task.done_at ? "text-muted line-through" : "text-sm"}>{task.title}</span>} checked={!!task.done_at} disabled={!editable || toggle.isPending}
              onChange={(e) => toggle.mutate({ id: task.id, done: e.target.checked })} className="min-w-0 flex-1" />
            <span className="hidden shrink-0 text-xs text-muted sm:block">{task.assignee_name}</span>
            {task.due_date && <span className={`tnum shrink-0 text-xs ${task.overdue ? "font-medium text-bad" : "text-muted"}`}>{formatDate(task.due_date)}</span>}
            {editable && <IconButton label={t("common.remove")} onClick={() => remove.mutate(task.id)}><Trash2 className="h-4 w-4" /></IconButton>}
          </li>
        ))}
      </ul>
      {editable && (
        <form className="mt-3 grid gap-2 sm:grid-cols-[1fr_10rem_9rem_auto]" onSubmit={(e) => { e.preventDefault(); if (title.trim()) add.mutate(); }}>
          <Input aria-label={t("tasks.new")} placeholder={t("tasks.new")} maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} />
          <PersonSelect value={assigneeId} onChange={setAssigneeId} />
          <Input type="date" aria-label={t("tasks.due")} value={due} onChange={(e) => setDue(e.target.value)} />
          <Button type="submit" variant="secondary" loading={add.isPending} disabled={!title.trim()}><Plus className="h-4 w-4" />{t("common.add")}</Button>
        </form>
      )}
    </Card>
  );
}
