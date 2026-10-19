import { type FormEvent, useEffect, useState } from "react";

import { api, Button, Drawer, Field, FormGrid, Input, NumberInput, orNull, Select, Textarea, toast, unwrap, useFormState, useMutation, useTranslation } from "@/sdk";

import { useRefresh, useStaff, useTemplates } from "../hooks";
import { formatClock, LONG_MINUTES, parseDuration } from "../lib";
import { BILLING_MODES, PROJECT_STATES, type Project } from "../types";
import { ClientPicker } from "./ClientPicker";
import { ServiceItemPicker } from "./ServiceItemPicker";

const blank = { code: "", name: "", mode: "time_and_materials", hours: "", amount: "", fee: "", cap: "", template: "", manager: "", branch: "", starts: "", ends: "", notes: "", status: "active" };

/** Create a project, or change one (its client and code stay as they were). */
export function ProjectForm({ open, onClose, companyId, branches, project, onSaved }: {
  open: boolean; onClose: () => void; companyId: string; branches: { id: string; name: string }[]; project?: Project | null; onSaved?: (p: Project) => void;
}) {
  const { t } = useTranslation("timebilling");
  const refresh = useRefresh();
  const staff = useStaff(companyId);
  const templates = useTemplates(companyId);
  const f = useFormState(blank);
  const [client, setClient] = useState({ id: "", name: "" });
  const [service, setService] = useState("");
  const { reset, set } = f;
  useEffect(() => {
    if (!open) return;
    reset();
    if (project) {
      set("code", project.code); set("name", project.name); set("mode", project.billing_mode);
      set("hours", project.budget_minutes ? formatClock(project.budget_minutes) : ""); set("amount", project.budget_amount ?? ""); set("fee", project.fixed_fee ?? ""); set("cap", project.fee_cap ?? "");
      set("manager", project.manager_id ?? ""); set("branch", project.branch_id ?? ""); set("starts", project.starts_on ?? ""); set("ends", project.ends_on ?? "");
      set("notes", project.notes ?? ""); set("status", project.status);
      setClient({ id: project.client_id, name: project.client_name });
      setService(project.service_product_id ?? "");
    } else {
      setClient({ id: "", name: "" });
      setService("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, project?.id]);

  const budget = parseDuration(f.values.hours, LONG_MINUTES);
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => {
      const v = f.values;
      const shared = {
        billing_mode: v.mode as (typeof BILLING_MODES)[number], budget_minutes: budget || null, budget_amount: orNull(v.amount),
        fixed_fee: v.mode === "fixed_fee" ? orNull(v.fee) : null, fee_cap: v.mode === "capped_fee" ? orNull(v.cap) : null, service_product_id: service || null, manager_id: v.manager || null,
        starts_on: v.starts || null, ends_on: v.ends || null, notes: orNull(v.notes), name: v.name.trim(),
      };
      return project
        ? unwrap(api.PATCH("/api/v1/timebilling/projects/{project_id}", { params: { path: { project_id: project.id } }, body: { ...shared, status: v.status as (typeof PROJECT_STATES)[number] } }))
        : unwrap(api.POST("/api/v1/timebilling/projects", { body: { ...shared, company_id: companyId, client_id: client.id, code: v.code.trim(), branch_id: v.branch || null, template_id: v.template || null } }));
    },
    onSuccess: (p) => { void refresh(); toast(t(project ? "projects.updated" : "projects.created", { name: p.name }), "ok"); onSaved?.(p); onClose(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  const budgetBad = f.values.hours !== "" && budget === null;

  return (
    <Drawer open={open} onClose={onClose} title={t(project ? "projects.edit" : "projects.new")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="project-form" loading={save.isPending} disabled={(!project && !client.id) || budgetBad}>{t("save")}</Button></>}>
      <form id="project-form" onSubmit={submit} className="space-y-4">
        <Field label={t("client")} required error={f.error("client_id")}><ClientPicker value={client.id} label={client.name} disabled={!!project} onChange={(id, name) => setClient({ id, name })} /></Field>
        <FormGrid>
          <Field label={t("projects.code")} required error={f.error("code")} hint={project ? undefined : t("projects.codeHint")}><Input {...f.bind("code")} maxLength={20} required disabled={!!project} className="font-mono" /></Field>
          <Field label={t("projects.name")} required error={f.error("name")}><Input {...f.bind("name")} maxLength={200} required /></Field>
        </FormGrid>
        {!project && !!templates.data?.length && (
          <Field label={t("projects.template")} hint={t("projects.templateHint")}>
            <Select value={f.values.template} onChange={(e) => {
              const found = templates.data?.find((x) => x.id === e.target.value);
              f.set("template", e.target.value);
              if (found) { f.set("mode", found.billing_mode); if (found.budget_minutes) f.set("hours", formatClock(found.budget_minutes)); }
            }}><option value="">{t("projects.noTemplate")}</option>{templates.data.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</Select>
          </Field>
        )}
        <FormGrid>
          <Field label={t("projects.billingMode")} error={f.error("billing_mode")} hint={t(`projects.modeHint.${f.values.mode}`)}>
            <Select {...f.bind("mode")}>{BILLING_MODES.map((m) => <option key={m} value={m}>{t(`projects.mode.${m}`)}</option>)}</Select>
          </Field>
          {project && <Field label={t("status")} error={f.error("status")}><Select {...f.bind("status")}>{PROJECT_STATES.map((s) => <option key={s} value={s}>{t(`projects.state.${s}`)}</option>)}</Select></Field>}
          {!project && branches.length > 1 && (
            <Field label={t("branch")} hint={t("projects.branchHint")} error={f.error("branch_id")}>
              <Select {...f.bind("branch")}><option value="">{t("projects.allBranches")}</option>{branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</Select>
            </Field>
          )}
        </FormGrid>
        {f.values.mode === "fixed_fee" && <Field label={t("projects.fixedFee")} required hint={t("projects.fixedFeeHint")} error={f.error("fixed_fee")}><NumberInput value={f.values.fee} onChange={(v) => f.set("fee", v)} required /></Field>}
        {f.values.mode === "capped_fee" && <Field label={t("projects.feeCap")} required hint={t("projects.feeCapHint")} error={f.error("fee_cap")}><NumberInput value={f.values.cap} onChange={(v) => f.set("cap", v)} required /></Field>}
        <FormGrid>
          <Field label={t("projects.budgetHours")} hint={t("projects.budgetHoursHint")} error={f.error("budget_minutes") ?? (budgetBad ? t("timeInvalid") : null)}><Input {...f.bind("hours")} placeholder="40:00" /></Field>
          <Field label={t("projects.budgetAmount")} hint={t("projects.budgetAmountHint")} error={f.error("budget_amount")}><NumberInput value={f.values.amount} onChange={(v) => f.set("amount", v)} /></Field>
        </FormGrid>
        <Field label={t("projects.serviceItem")} hint={t("projects.serviceItemHint")} error={f.error("service_product_id")}><ServiceItemPicker value={service} onChange={setService} /></Field>
        <Field label={t("projects.manager")} error={f.error("manager_id")}>
          <Select {...f.bind("manager")}><option value="">—</option>{(staff.data ?? []).filter((s) => s.active).map((s) => <option key={s.user_id} value={s.user_id}>{s.name}</option>)}</Select>
        </Field>
        <FormGrid>
          <Field label={t("projects.starts")} error={f.error("starts_on")}><Input type="date" {...f.bind("starts")} /></Field>
          <Field label={t("projects.ends")} error={f.error("ends_on")}><Input type="date" {...f.bind("ends")} min={f.values.starts || undefined} /></Field>
        </FormGrid>
        <Field label={t("note")} error={f.error("notes")}><Textarea {...f.bind("notes")} maxLength={2000} /></Field>
      </form>
    </Drawer>
  );
}
