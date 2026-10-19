/** Editing a job's own details: the form, and the request that carries only what changed. */
import type { Schemas } from "@/sdk";

import type { Job } from "./types";

export interface EditForm {
  title: string;
  description: string;
  condition: string;
  customerId: string;
  customerName: string;
  customerPhone: string;
  assetId: string;
  assigneeId: string;
  promised: string;
}

export const editForm = (job: Job): EditForm => ({
  title: job.title, description: job.description ?? "", condition: job.condition_notes ?? "", customerId: job.customer_id ?? "",
  customerName: job.customer_name ?? "", customerPhone: job.customer_phone ?? "", assetId: job.asset?.id ?? "", assigneeId: job.assignee_id ?? "",
  promised: job.promised_at ?? "",
});

const text = (value: string): string | null => value.trim() || null;

/** Only the fields that differ from the job. A customer picked from the list is sent as its id (the server takes name and phone from the record). */
export function jobPatch(job: Job, form: EditForm): Schemas["JobUpdate"] {
  const was = editForm(job);
  const patch: Schemas["JobUpdate"] = {};
  if (form.title.trim() !== was.title) patch.title = form.title.trim();
  if (form.description.trim() !== was.description.trim()) patch.description = text(form.description);
  if (form.condition.trim() !== was.condition.trim()) patch.condition_notes = text(form.condition);
  if (form.customerId !== was.customerId) {
    patch.customer_id = form.customerId || null;
    if (!form.customerId) { patch.customer_name = text(form.customerName); patch.customer_phone = text(form.customerPhone); }
  } else if (!form.customerId && (form.customerName.trim() !== was.customerName.trim() || form.customerPhone.trim() !== was.customerPhone.trim())) {
    patch.customer_name = text(form.customerName);
    patch.customer_phone = text(form.customerPhone);
  }
  if (form.assetId !== was.assetId) patch.asset_id = form.assetId || null;
  if (form.assigneeId !== was.assigneeId) patch.assignee_id = form.assigneeId || null;
  if (form.promised !== was.promised) patch.promised_at = form.promised || null;
  return patch;
}
