import { type FormEvent, useEffect, useState } from "react";

import { api, Button, Field, FormGrid, Input, Modal, Switch, Textarea, toast, today, unwrap, useFormState, useMutation, useTranslation } from "@/sdk";

import { useRefresh } from "../hooks";
import { formatClock, formatDuration, parseDuration, snapMinutes } from "../lib";
import type { Entry, Project } from "../types";
import { ProjectPicker } from "./ProjectPicker";
import { TaskInput } from "./TaskInput";

/** Log (or correct) one piece of work with a note: project, day, how long, what was done. */
export function LogTimeDialog({ open, onClose, companyId, entry, day, step }: { open: boolean; onClose: () => void; companyId: string; entry?: Entry | null; day: string; step: number }) {
  const { t } = useTranslation("timebilling");
  const refresh = useRefresh();
  const f = useFormState({ date: day, time: "", task: "", note: "" });
  const [project, setProject] = useState<Project | null>(null);
  const [billable, setBillable] = useState(true);
  const { reset, set } = f;
  useEffect(() => {
    if (!open) return;
    reset();
    set("date", entry?.work_date ?? day);
    set("time", entry ? formatClock(entry.minutes) : "");
    set("task", entry?.task ?? "");
    set("note", entry?.note ?? "");
    setBillable(entry?.billable ?? true);
    setProject(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, entry?.id]);

  const parsed = parseDuration(f.values.time);
  const minutes = parsed ? snapMinutes(parsed, step) : null;
  const projectId = project?.id ?? entry?.project_id ?? "";
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => {
      const body = { project_id: projectId, work_date: f.values.date, minutes: minutes ?? 0, task: f.values.task.trim() || null, note: f.values.note.trim() || null, billable };
      return entry
        ? unwrap(api.PATCH("/api/v1/timebilling/entries/{entry_id}", { params: { path: { entry_id: entry.id } }, body }))
        : unwrap(api.POST("/api/v1/timebilling/entries", { body }));
    },
    onSuccess: () => { void refresh(); toast(t(entry ? "log.updated" : "log.saved"), "ok"); onClose(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); if (projectId && minutes) save.mutate(); };

  return (
    <Modal open={open} onClose={onClose} title={t(entry ? "log.editTitle" : "log.title")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="log-time" loading={save.isPending} disabled={!projectId || !minutes}>{t("save")}</Button></>}>
      <form id="log-time" onSubmit={submit} className="space-y-4">
        <Field label={t("projectField")} required error={f.error("project_id")}>
          <ProjectPicker companyId={companyId} value={projectId} label={project ? `${project.code} · ${project.name}` : entry ? `${entry.project_code} · ${entry.project_name}` : undefined} onChange={setProject} />
        </Field>
        <FormGrid>
          <Field label={t("date")} required error={f.error("work_date")}><Input type="date" max={today()} {...f.bind("date")} required /></Field>
          <Field label={t("time")} required hint={minutes && minutes !== parsed ? t("snappedTo", { time: formatDuration(minutes) }) : t("timeHint")} error={f.error("minutes") ?? (f.values.time && parsed === null ? t("timeInvalid") : null)}>
            <Input {...f.bind("time")} placeholder="1:30" required />
          </Field>
        </FormGrid>
        <Field label={t("task")} error={f.error("task")}><TaskInput companyId={companyId} value={f.values.task} onChange={(v) => f.set("task", v)} /></Field>
        <Field label={t("note")} error={f.error("note")}><Textarea {...f.bind("note")} maxLength={1000} placeholder={t("noteHint")} /></Field>
        <div className="flex items-center gap-2 text-sm"><Switch checked={billable} onChange={setBillable} label={t("billable")} />{t("billable")}</div>
      </form>
    </Modal>
  );
}
