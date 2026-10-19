import { useEffect, useState } from "react";

import { api, Button, Drawer, Field, FormGrid, Input, Textarea, unwrap, useTranslation } from "@/sdk";

import { editForm, type EditForm, jobPatch } from "../editJob";
import { useJobAction, useUnit } from "../hooks";
import type { Job } from "../types";
import { AssetPicker, CustomerPicker, PersonSelect } from "./pickers";

/** Change a job's title, notes, customer, item, person in charge or promised date. */
export function EditJobDrawer({ job, open, onClose }: { job: Job; open: boolean; onClose: () => void }) {
  const { t } = useTranslation("jobs");
  const hasCustomers = useUnit("crm");
  const [form, setForm] = useState<EditForm>(() => editForm(job));
  useEffect(() => { if (open) setForm(editForm(job)); }, [open, job]);
  const set = (patch: Partial<EditForm>) => setForm((f) => ({ ...f, ...patch }));
  const patch = jobPatch(job, form);
  const save = useJobAction(job.id, () => unwrap(api.PATCH("/api/v1/jobs/jobs/{job_id}", { params: { path: { job_id: job.id } }, body: patch })), { done: t("edit.saved"), onDone: onClose });
  return (
    <Drawer open={open} onClose={onClose} title={t("edit.title", { number: job.number })}
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button loading={save.isPending} disabled={Object.keys(patch).length === 0 || !form.title.trim()} onClick={() => save.mutate()}>{t("common.save")}</Button></>}>
      <div className="space-y-4">
        <Field label={t("receive.title")} required><Input maxLength={200} value={form.title} onChange={(e) => set({ title: e.target.value })} /></Field>
        <Field label={t("receive.details")}><Textarea maxLength={4000} value={form.description} onChange={(e) => set({ description: e.target.value })} /></Field>
        <Field label={t("receive.condition")}><Textarea maxLength={4000} value={form.condition} onChange={(e) => set({ condition: e.target.value })} /></Field>
        {hasCustomers && <Field label={t("receive.customer")}><CustomerPicker value={form.customerId} onChange={(id) => set({ customerId: id })} /></Field>}
        {!form.customerId && (
          <FormGrid>
            <Field label={t("receive.customerName")}><Input maxLength={160} value={form.customerName} onChange={(e) => set({ customerName: e.target.value })} /></Field>
            <Field label={t("receive.customerPhone")}><Input type="tel" maxLength={40} value={form.customerPhone} onChange={(e) => set({ customerPhone: e.target.value })} /></Field>
          </FormGrid>
        )}
        <Field label={t("edit.item")}><AssetPicker value={form.assetId} onChange={(id) => set({ assetId: id })} /></Field>
        <FormGrid>
          <Field label={t("receive.assignee")}><PersonSelect value={form.assigneeId} onChange={(id) => set({ assigneeId: id })} /></Field>
          <Field label={t("receive.promised")}><Input type="date" value={form.promised} onChange={(e) => set({ promised: e.target.value })} /></Field>
        </FormGrid>
      </div>
    </Drawer>
  );
}
