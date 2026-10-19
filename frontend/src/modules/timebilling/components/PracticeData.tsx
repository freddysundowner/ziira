import { Plus } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";

import { api, Badge, Button, ConfirmDialog, DataTable, Field, FormGrid, Input, Modal, NumberInput, Select, Switch, Textarea, toast, unwrap, useFormState, useMutation, useQuery, useTranslation } from "@/sdk";

import { useActivities, useRefresh, useTemplates } from "../hooks";
import { BILLING_MODES, FREQUENCIES, type Activity, type Snippet, type Template } from "../types";
import { formatClock, LONG_MINUTES, parseDuration } from "../lib";

const lines = (text: string): string[] => text.split("\n").map((x) => x.trim()).filter(Boolean);

/** Engagement templates, activity names and standard invoice wording: the data a practice starts from and edits. */
export function PracticeData({ companyId, part }: { companyId: string; part: "templates" | "activities" | "wording" }) {
  return part === "templates" ? <Templates companyId={companyId} /> : part === "activities" ? <Activities companyId={companyId} /> : <Wording companyId={companyId} />;
}

function Header({ title, hint, onAdd, addLabel }: { title: string; hint: string; onAdd: () => void; addLabel: string }) {
  return (
    <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
      <div><h2 className="text-sm font-semibold">{title}</h2><p className="text-sm text-muted">{hint}</p></div>
      <Button onClick={onAdd}><Plus className="h-4 w-4" />{addLabel}</Button>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------- templates
function Templates({ companyId }: { companyId: string }) {
  const { t } = useTranslation("timebilling");
  const refresh = useRefresh();
  const list = useTemplates(companyId, true);
  const [form, setForm] = useState<{ row: Template | null } | null>(null);
  const [removing, setRemoving] = useState<Template | null>(null);
  const remove = useMutation({
    mutationFn: (row: Template) => unwrap(api.DELETE("/api/v1/timebilling/templates/{template_id}", { params: { path: { template_id: row.id } } })),
    onSuccess: () => { setRemoving(null); void refresh(); },
  });
  return (
    <>
      <Header title={t("practice.templates")} hint={t("practice.templatesHint")} addLabel={t("practice.addTemplate")} onAdd={() => setForm({ row: null })} />
      <DataTable rows={list.data} loading={list.isLoading} error={list.error?.message} onRetry={() => void list.refetch()} rowKey={(r) => r.id} empty={{ title: t("practice.templatesEmpty") }}
        columns={[
          { header: t("practice.name"), cell: (r) => <span><span className="font-medium">{r.name}</span>{r.description && <span className="block max-w-md truncate text-xs text-muted">{r.description}</span>}</span> },
          { header: t("projects.billingMode"), hideBelow: "sm", cell: (r) => <Badge>{t(`projects.mode.${r.billing_mode}`)}</Badge> },
          { header: t("practice.repeats"), hideBelow: "md", cell: (r) => (r.frequency ? t(`work.every.${r.frequency}`) : "—") },
          { header: t("practice.checklist"), hideBelow: "md", align: "right", cell: (r) => r.checklist.length },
          { header: "", align: "right", cell: (r) => <span className="flex justify-end gap-1"><Button size="sm" variant="ghost" onClick={() => setForm({ row: r })}>{t("edit")}</Button><Button size="sm" variant="ghost" onClick={() => setRemoving(r)}>{t("delete")}</Button></span> },
        ]} />
      <TemplateForm companyId={companyId} state={form} onClose={() => setForm(null)} />
      <ConfirmDialog open={!!removing} onClose={() => setRemoving(null)} onConfirm={() => removing && remove.mutate(removing)} busy={remove.isPending} danger title={t("delete")} message={t("practice.deleteAsk")} confirmLabel={t("delete")} />
    </>
  );
}

function TemplateForm({ companyId, state, onClose }: { companyId: string; state: { row: Template | null } | null; onClose: () => void }) {
  const { t } = useTranslation("timebilling");
  const refresh = useRefresh();
  const row = state?.row ?? null;
  const f = useFormState({ name: "", description: "", mode: "time_and_materials", hours: "", freq: "", day: "15", month: "6", lead: "14", items: "", miles: "" });
  const { reset, set } = f;
  useEffect(() => {
    if (!state) return;
    reset();
    if (row) {
      set("name", row.name); set("description", row.description ?? ""); set("mode", row.billing_mode); set("hours", row.budget_minutes ? formatClock(row.budget_minutes) : "");
      set("freq", row.frequency ?? ""); set("day", String(row.due_day ?? 15)); set("month", String(row.due_month ?? 6)); set("lead", String(row.lead_days));
      set("items", row.checklist.join("\n")); set("miles", row.milestones.map((m) => `${m.name} | ${m.percent}`).join("\n"));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state]);
  const hours = parseDuration(f.values.hours, LONG_MINUTES);
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => {
      const v = f.values;
      const body = {
        company_id: companyId, name: v.name.trim(), description: v.description.trim() || null, billing_mode: v.mode as "fixed_fee", budget_minutes: hours || null,
        frequency: (v.freq || null) as "monthly" | null, due_day: v.freq ? Number(v.day) || 1 : null, due_month: v.freq && v.freq !== "monthly" ? Number(v.month) || 1 : null, lead_days: Number(v.lead) || 0,
        checklist: lines(v.items), milestones: lines(v.miles).map((x) => { const [name = "", pct = "0"] = x.split("|").map((p) => p.trim()); return { name, percent: pct.replace("%", "") || "0" }; }), active: true,
      };
      return row ? unwrap(api.PUT("/api/v1/timebilling/templates/{template_id}", { params: { path: { template_id: row.id } }, body })) : unwrap(api.POST("/api/v1/timebilling/templates", { body }));
    },
    onSuccess: () => { void refresh(); toast(t("practice.saved"), "ok"); onClose(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  return (
    <Modal open={!!state} onClose={onClose} title={t(row ? "practice.editTemplate" : "practice.addTemplate")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="template-form" loading={save.isPending} disabled={!f.values.name.trim() || (f.values.hours !== "" && hours === null)}>{t("save")}</Button></>}>
      <form id="template-form" onSubmit={submit} className="space-y-4">
        <Field label={t("practice.name")} required error={f.error("name")}><Input {...f.bind("name")} maxLength={120} required data-autofocus /></Field>
        <Field label={t("practice.description")} error={f.error("description")}><Input {...f.bind("description")} maxLength={500} /></Field>
        <FormGrid>
          <Field label={t("projects.billingMode")} hint={t(`projects.modeHint.${f.values.mode}`)}><Select {...f.bind("mode")}>{BILLING_MODES.map((m) => <option key={m} value={m}>{t(`projects.mode.${m}`)}</option>)}</Select></Field>
          <Field label={t("projects.budgetHours")} error={f.error("budget_minutes")}><Input {...f.bind("hours")} placeholder="40:00" /></Field>
        </FormGrid>
        <FormGrid>
          <Field label={t("work.repeatsEvery")}><Select {...f.bind("freq")}><option value="">{t("practice.noRepeat")}</option>{FREQUENCIES.map((x) => <option key={x} value={x}>{t(`work.every.${x}`)}</option>)}</Select></Field>
          {f.values.freq && <Field label={t("work.dueDay")}><NumberInput value={f.values.day} onChange={(v) => f.set("day", v.replace(/\./g, ""))} /></Field>}
        </FormGrid>
        {f.values.freq && f.values.freq !== "monthly" && <Field label={t("work.dueMonth")}><Select {...f.bind("month")}>{Array.from({ length: 12 }, (_, i) => <option key={i + 1} value={i + 1}>{t(`months.${i + 1}`)}</option>)}</Select></Field>}
        {f.values.freq && <Field label={t("work.lead")} hint={t("work.leadHint")}><NumberInput value={f.values.lead} onChange={(v) => f.set("lead", v.replace(/\./g, ""))} /></Field>}
        <Field label={t("work.checklist")} hint={t("work.checklistHint")}><Textarea rows={5} {...f.bind("items")} /></Field>
        {f.values.mode === "fixed_fee" && <Field label={t("practice.milestones")} hint={t("practice.milestonesHint")} error={f.error("milestones")}><Textarea rows={4} {...f.bind("miles")} placeholder={"Kick-off | 30\nDraft | 40\nFinal | 30"} /></Field>}
      </form>
    </Modal>
  );
}

// -------------------------------------------------------------------------------------------------- activities
function Activities({ companyId }: { companyId: string }) {
  const { t } = useTranslation("timebilling");
  const refresh = useRefresh();
  const list = useActivities(companyId);
  const [form, setForm] = useState<{ row: Activity | null } | null>(null);
  const remove = useMutation({
    mutationFn: (row: Activity) => unwrap(api.DELETE("/api/v1/timebilling/activities/{activity_id}", { params: { path: { activity_id: row.id } } })),
    onSuccess: () => void refresh(),
  });
  return (
    <>
      <Header title={t("practice.activities")} hint={t("practice.activitiesHint")} addLabel={t("practice.addActivity")} onAdd={() => setForm({ row: null })} />
      <DataTable rows={list.data} loading={list.isLoading} error={list.error?.message} onRetry={() => void list.refetch()} rowKey={(r) => r.id} searchText={(r) => `${r.name} ${r.group_name ?? ""}`}
        empty={{ title: t("practice.activitiesEmpty") }}
        columns={[
          { header: t("practice.name"), sortValue: (r) => r.name, cell: (r) => <span className="font-medium">{r.name}</span> },
          { header: t("practice.group"), hideBelow: "sm", sortValue: (r) => r.group_name ?? "", cell: (r) => r.group_name ?? "—" },
          { header: t("billable"), hideBelow: "sm", cell: (r) => <Badge tone={r.billable ? "ok" : "neutral"}>{t(r.billable ? "yes" : "no")}</Badge> },
          { header: "", align: "right", cell: (r) => <span className="flex justify-end gap-1"><Button size="sm" variant="ghost" onClick={() => setForm({ row: r })}>{t("edit")}</Button><Button size="sm" variant="ghost" onClick={() => remove.mutate(r)}>{t("delete")}</Button></span> },
        ]} />
      <ActivityForm companyId={companyId} state={form} onClose={() => setForm(null)} />
    </>
  );
}

function ActivityForm({ companyId, state, onClose }: { companyId: string; state: { row: Activity | null } | null; onClose: () => void }) {
  const { t } = useTranslation("timebilling");
  const refresh = useRefresh();
  const row = state?.row ?? null;
  const f = useFormState({ name: "", group: "" });
  const [billable, setBillable] = useState(true);
  const { reset, set } = f;
  useEffect(() => { if (state) { reset(); set("name", row?.name ?? ""); set("group", row?.group_name ?? ""); setBillable(row?.billable ?? true); } }, [state]); // eslint-disable-line react-hooks/exhaustive-deps
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => {
      const body = { company_id: companyId, name: f.values.name.trim(), group_name: f.values.group.trim() || null, billable, sort_order: row?.sort_order ?? 0, active: true };
      return row ? unwrap(api.PUT("/api/v1/timebilling/activities/{activity_id}", { params: { path: { activity_id: row.id } }, body })) : unwrap(api.POST("/api/v1/timebilling/activities", { body }));
    },
    onSuccess: () => { void refresh(); onClose(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  return (
    <Modal open={!!state} onClose={onClose} title={t(row ? "practice.editActivity" : "practice.addActivity")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="activity-form" loading={save.isPending} disabled={!f.values.name.trim()}>{t("save")}</Button></>}>
      <form id="activity-form" onSubmit={submit} className="space-y-4">
        <Field label={t("practice.name")} required error={f.error("name")}><Input {...f.bind("name")} maxLength={120} required data-autofocus /></Field>
        <Field label={t("practice.group")} error={f.error("group_name")}><Input {...f.bind("group")} maxLength={80} /></Field>
        <div className="flex items-center gap-2 text-sm"><Switch checked={billable} onChange={setBillable} label={t("billable")} />{t("practice.billableByDefault")}</div>
      </form>
    </Modal>
  );
}

// ------------------------------------------------------------------------------------------------------ wording
function Wording({ companyId }: { companyId: string }) {
  const { t } = useTranslation("timebilling");
  const refresh = useRefresh();
  const list = useQuery<Snippet[]>({
    queryKey: ["timebilling", "snippets", companyId, "all"], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/snippets", { params: { query: { company_id: companyId } } })),
  });
  const [form, setForm] = useState<{ row: Snippet | null } | null>(null);
  const remove = useMutation({
    mutationFn: (row: Snippet) => unwrap(api.DELETE("/api/v1/timebilling/snippets/{snippet_id}", { params: { path: { snippet_id: row.id } } })),
    onSuccess: () => void refresh(),
  });
  return (
    <>
      <Header title={t("practice.wording")} hint={t("practice.wordingHint")} addLabel={t("practice.addWording")} onAdd={() => setForm({ row: null })} />
      <DataTable rows={list.data} loading={list.isLoading} error={list.error?.message} onRetry={() => void list.refetch()} rowKey={(r) => r.id} empty={{ title: t("practice.wordingEmpty") }}
        columns={[
          { header: t("practice.name"), cell: (r) => <span><span className="font-medium">{r.name}</span><span className="block max-w-xl truncate text-xs text-muted">{r.body}</span></span> },
          { header: t("practice.language"), hideBelow: "sm", cell: (r) => <Badge>{r.language}</Badge> },
          { header: "", align: "right", cell: (r) => <span className="flex justify-end gap-1"><Button size="sm" variant="ghost" onClick={() => setForm({ row: r })}>{t("edit")}</Button><Button size="sm" variant="ghost" onClick={() => remove.mutate(r)}>{t("delete")}</Button></span> },
        ]} />
      <WordingForm companyId={companyId} state={form} onClose={() => setForm(null)} />
    </>
  );
}

function WordingForm({ companyId, state, onClose }: { companyId: string; state: { row: Snippet | null } | null; onClose: () => void }) {
  const { t } = useTranslation("timebilling");
  const refresh = useRefresh();
  const row = state?.row ?? null;
  const f = useFormState({ name: "", language: "en", body: "" });
  const { reset, set } = f;
  useEffect(() => { if (state) { reset(); set("name", row?.name ?? ""); set("language", row?.language ?? "en"); set("body", row?.body ?? ""); } }, [state]); // eslint-disable-line react-hooks/exhaustive-deps
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => {
      const body = { company_id: companyId, kind: "invoice_note" as const, name: f.values.name.trim(), language: f.values.language, body: f.values.body.trim(), active: true };
      return row ? unwrap(api.PUT("/api/v1/timebilling/snippets/{snippet_id}", { params: { path: { snippet_id: row.id } }, body })) : unwrap(api.POST("/api/v1/timebilling/snippets", { body }));
    },
    onSuccess: () => { void refresh(); onClose(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  return (
    <Modal open={!!state} onClose={onClose} title={t(row ? "practice.editWording" : "practice.addWording")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="wording-form" loading={save.isPending} disabled={!f.values.name.trim() || !f.values.body.trim()}>{t("save")}</Button></>}>
      <form id="wording-form" onSubmit={submit} className="space-y-4">
        <FormGrid>
          <Field label={t("practice.name")} required error={f.error("name")}><Input {...f.bind("name")} maxLength={120} required data-autofocus /></Field>
          <Field label={t("practice.language")}><Select {...f.bind("language")}><option value="en">English</option><option value="sw">Kiswahili</option></Select></Field>
        </FormGrid>
        <Field label={t("practice.text")} required hint={t("practice.textHint")} error={f.error("body")}><Textarea rows={4} {...f.bind("body")} maxLength={500} required /></Field>
      </form>
    </Modal>
  );
}
