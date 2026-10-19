import { type FormEvent, useEffect, useState } from "react";

import { api, Badge, Button, Card, EmptyState, Field, FormGrid, Input, Modal, NumberInput, Select, Skeleton, Switch, Textarea, toast, today, unwrap, useCan, useFormState, useMutation, useQuery, useTranslation } from "@/sdk";

import { useRefresh, useStaff } from "../hooks";
import { FREQUENCIES, type Project, type Recurrence } from "../types";
import { TaskCard } from "./TaskCard";

const lines = (text: string): string[] => text.split("\n").map((x) => x.trim()).filter(Boolean);

/** The engagement's repeating work (monthly close, annual return) and its dated tasks, each with a checklist. */
export function WorkTab({ project }: { project: Project }) {
  const { t } = useTranslation("timebilling");
  const canManage = useCan("projects.manage");
  const refresh = useRefresh();
  const [form, setForm] = useState<"repeat" | "once" | null>(null);
  const tasks = useQuery({
    queryKey: ["timebilling", "tasks", project.id],
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/tasks", { params: { query: { project_id: project.id, limit: 100 } } })),
  });
  const repeats = useQuery({
    queryKey: ["timebilling", "recurrences", project.id],
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/recurrences", { params: { query: { project_id: project.id } } })),
  });
  const toggle = useMutation({
    mutationFn: (r: Recurrence) => unwrap(api.PATCH("/api/v1/timebilling/recurrences/{recurrence_id}", { params: { path: { recurrence_id: r.id } }, body: { active: !r.active } })),
    onSuccess: () => void refresh(),
  });
  if (tasks.isLoading || repeats.isLoading) return <Skeleton className="h-40 w-full" />;
  const open = (tasks.data ?? []).filter((x) => x.status === "open");
  const closed = (tasks.data ?? []).filter((x) => x.status !== "open");
  return (
    <div className="space-y-4">
      {canManage && (
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => setForm("repeat")}>{t("work.addRepeat")}</Button>
          <Button variant="secondary" onClick={() => setForm("once")}>{t("work.addOnce")}</Button>
        </div>
      )}
      {(repeats.data ?? []).length > 0 && (
        <Card title={t("work.repeats")}>
          <ul className="divide-y divide-line text-sm">
            {repeats.data!.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <span><span className="font-medium">{r.name}</span><span className="block text-xs text-muted">{t(`work.freq.${r.frequency}`, { day: r.due_day, month: r.due_month ?? 1 })} · {t("work.leadDays", { count: r.lead_days })}</span></span>
                <span className="flex items-center gap-2">{!r.active && <Badge>{t("work.paused")}</Badge>}{canManage && <Switch checked={r.active} onChange={() => toggle.mutate(r)} label={t("work.active")} />}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
      {open.length === 0 && closed.length === 0 && <EmptyState title={t("work.empty")} hint={t("work.emptyHint")} />}
      <div className="space-y-3">{open.map((x) => <TaskCard key={x.id} task={x} />)}</div>
      {closed.length > 0 && (
        <details className="text-sm"><summary className="cursor-pointer font-medium">{t("work.finished", { count: closed.length })}</summary><div className="mt-3 space-y-3">{closed.map((x) => <TaskCard key={x.id} task={x} />)}</div></details>
      )}
      <WorkForm project={project} mode={form} onClose={() => setForm(null)} />
    </div>
  );
}

function WorkForm({ project, mode, onClose }: { project: Project; mode: "repeat" | "once" | null; onClose: () => void }) {
  const { t } = useTranslation("timebilling");
  const refresh = useRefresh();
  const staff = useStaff(project.company_id);
  const f = useFormState({ name: "", frequency: "monthly", day: "15", month: "6", lead: "14", due: today(), who: project.manager_id ?? "", items: "" });
  const { reset, set } = f;
  useEffect(() => { if (mode) { reset(); set("who", project.manager_id ?? ""); } }, [mode]); // eslint-disable-line react-hooks/exhaustive-deps
  const save = useMutation({
    meta: { silent: true },
    mutationFn: async () => {
      const v = f.values;
      await (mode === "repeat"
        ? unwrap(api.POST("/api/v1/timebilling/projects/{project_id}/recurrences", { params: { path: { project_id: project.id } }, body: {
          name: v.name.trim(), frequency: v.frequency as "monthly", due_day: Number(v.day) || 1, due_month: v.frequency === "monthly" ? null : Number(v.month) || 1, lead_days: Number(v.lead) || 0,
          assignee_id: v.who || null, checklist: lines(v.items) } }))
        : unwrap(api.POST("/api/v1/timebilling/projects/{project_id}/tasks", { params: { path: { project_id: project.id } }, body: { name: v.name.trim(), due_on: v.due, assignee_id: v.who || null, checklist: lines(v.items) } })));
    },
    onSuccess: () => { void refresh(); toast(t("work.saved"), "ok"); onClose(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  return (
    <Modal open={!!mode} onClose={onClose} title={t(mode === "repeat" ? "work.addRepeat" : "work.addOnce")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="work-form" loading={save.isPending} disabled={!f.values.name.trim()}>{t("save")}</Button></>}>
      <form id="work-form" onSubmit={submit} className="space-y-4">
        <Field label={t("work.name")} required error={f.error("name")}><Input {...f.bind("name")} maxLength={200} required placeholder={t("work.nameHint")} data-autofocus /></Field>
        {mode === "repeat" ? (
          <>
            <FormGrid>
              <Field label={t("work.repeatsEvery")} error={f.error("frequency")}><Select {...f.bind("frequency")}>{FREQUENCIES.map((x) => <option key={x} value={x}>{t(`work.every.${x}`)}</option>)}</Select></Field>
              <Field label={t("work.dueDay")} hint={t("work.dueDayHint")} error={f.error("due_day")}><NumberInput value={f.values.day} onChange={(v) => f.set("day", v.replace(/\./g, ""))} /></Field>
            </FormGrid>
            <FormGrid>
              {f.values.frequency !== "monthly" && <Field label={t("work.dueMonth")} hint={f.values.frequency === "quarterly" ? t("work.dueMonthQuarterly") : undefined} error={f.error("due_month")}><Select {...f.bind("month")}>{Array.from({ length: 12 }, (_, i) => <option key={i + 1} value={i + 1}>{t(`months.${i + 1}`)}</option>)}</Select></Field>}
              <Field label={t("work.lead")} hint={t("work.leadHint")} error={f.error("lead_days")}><NumberInput value={f.values.lead} onChange={(v) => f.set("lead", v.replace(/\./g, ""))} /></Field>
            </FormGrid>
          </>
        ) : <Field label={t("work.dueOn")} required error={f.error("due_on")}><Input type="date" {...f.bind("due")} required /></Field>}
        <Field label={t("work.assignee")} error={f.error("assignee_id")}><Select {...f.bind("who")}><option value="">—</option>{(staff.data ?? []).filter((s) => s.active).map((s) => <option key={s.user_id} value={s.user_id}>{s.name}</option>)}</Select></Field>
        <Field label={t("work.checklist")} hint={t("work.checklistHint")} error={f.error("checklist")}><Textarea rows={5} {...f.bind("items")} /></Field>
      </form>
    </Modal>
  );
}
