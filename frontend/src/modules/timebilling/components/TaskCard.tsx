import { useState } from "react";

import { Badge, Button, Checkbox, formatDate, Field, Input, Modal, api, toast, unwrap, useCan, useMutation, useTranslation } from "@/sdk";

import { useRefresh } from "../hooks";
import type { Task } from "../types";

/** One dated piece of work with its checklist: tick items, then mark it done (or skip it with a reason). */
export function TaskCard({ task, showProject = false }: { task: Task; showProject?: boolean }) {
  const { t } = useTranslation("timebilling");
  const refresh = useRefresh();
  const canManage = useCan("projects.manage");
  const [skipping, setSkipping] = useState(false);
  const [why, setWhy] = useState("");
  const path = { task_id: task.id };
  const open = task.status === "open";
  const tick = useMutation({
    mutationFn: (v: { index: number; done: boolean }) => unwrap(api.POST("/api/v1/timebilling/tasks/{task_id}/tick", { params: { path }, body: v })),
    onSuccess: () => void refresh(),
  });
  const finish = useMutation({
    mutationFn: (skipped: boolean) => unwrap(api.POST("/api/v1/timebilling/tasks/{task_id}/finish", { params: { path }, body: { skipped, note: skipped ? why.trim() : null } })),
    onSuccess: () => { setSkipping(false); setWhy(""); void refresh(); },
  });
  const reopen = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/timebilling/tasks/{task_id}/reopen", { params: { path } })),
    onSuccess: () => void refresh(),
  });
  const allDone = task.items.every((i) => i.done);
  return (
    <div className="rounded-xl border border-line bg-surface p-3 shadow-card">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-medium">{task.name}{task.period ? ` · ${task.period}` : ""}</p>
          <p className="text-xs text-muted">{showProject ? `${task.client_name || task.project_name} · ` : ""}{task.assignee_name || t("work.unassigned")}</p>
        </div>
        <div className="flex items-center gap-2">
          {task.overdue && <Badge tone="bad">{t("work.overdue")}</Badge>}
          {!open && <Badge tone={task.status === "done" ? "ok" : "neutral"}>{t(`work.status.${task.status}`)}</Badge>}
          <span className="tnum text-sm">{t("work.due", { date: formatDate(task.due_on) })}</span>
        </div>
      </div>
      {task.items.length > 0 && (
        <ul className="mt-2 space-y-1">
          {task.items.map((item, i) => (
            <li key={`${i}-${item.label}`}><Checkbox label={<span className={item.done ? "text-muted line-through" : ""}>{item.label}</span>} checked={item.done} disabled={!open || tick.isPending} onChange={(e) => tick.mutate({ index: i, done: e.target.checked })} /></li>
          ))}
        </ul>
      )}
      {task.note && <p className="mt-2 text-xs text-muted">{task.note}</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        {open && <Button size="sm" disabled={!allDone} loading={finish.isPending && !skipping} onClick={() => finish.mutate(false)}>{t("work.markDone")}</Button>}
        {open && <Button size="sm" variant="ghost" onClick={() => setSkipping(true)}>{t("work.skip")}</Button>}
        {!open && canManage && <Button size="sm" variant="ghost" loading={reopen.isPending} onClick={() => reopen.mutate()}>{t("work.reopen")}</Button>}
        {open && !allDone && <span className="self-center text-xs text-muted">{t("work.tickFirst")}</span>}
      </div>
      <Modal open={skipping} onClose={() => setSkipping(false)} title={t("work.skip")}
        footer={<><Button variant="secondary" onClick={() => setSkipping(false)}>{t("cancel")}</Button><Button disabled={!why.trim()} loading={finish.isPending} onClick={() => { finish.mutate(true); toast(t("work.skipped"), "ok"); }}>{t("work.skip")}</Button></>}>
        <Field label={t("work.skipReason")} required><Input value={why} maxLength={300} onChange={(e) => setWhy(e.target.value)} data-autofocus /></Field>
      </Modal>
    </div>
  );
}
