/** The "Receive an item" form as plain data: what it starts with, what is missing, and the request it makes. */
import type { Schemas } from "@/sdk";

import { cleanIdentifiers, type IdentifierRow } from "./lib";

export interface ReceiveForm {
  branchId: string;
  title: string;
  description: string;
  condition: string;
  promised: string;
  assigneeId: string;
  customerId: string;
  customerName: string;
  customerPhone: string;
  itemMode: "existing" | "new";
  assetId: string;
  newLabel: string;
  newKind: string;
  newRows: IdentifierRow[];
  checklist: string[];
  jobTypeCode: string;
  odometer: string;
  fuel: string;
  keyTag: string;
  belongings: string;
  signedBy: string;
}

export const emptyReceive = (branchId = ""): ReceiveForm => ({
  branchId, title: "", description: "", condition: "", promised: "", assigneeId: "", customerId: "", customerName: "", customerPhone: "",
  itemMode: "existing", assetId: "", newLabel: "", newKind: "", newRows: [{ name: "", value: "" }], checklist: [],
  jobTypeCode: "", odometer: "", fuel: "", keyTag: "", belongings: "", signedBy: "",
});

export type ReceiveProblem = "title" | "branch" | "newLabel";

/** What must still be filled in before the item can be taken in. */
export function receiveProblems(form: ReceiveForm): ReceiveProblem[] {
  const found: ReceiveProblem[] = [];
  if (!form.title.trim()) found.push("title");
  if (!form.branchId) found.push("branch");
  if (form.itemMode === "new" && form.newRows.some((r) => r.name.trim() || r.value.trim()) && !form.newLabel.trim()) found.push("newLabel");
  return found;
}

const text = (value: string): string | null => value.trim() || null;

export function buildJobBody(companyId: string, form: ReceiveForm): Schemas["JobIn"] {
  const items = form.checklist.map((l) => l.trim()).filter(Boolean);
  const newItem = form.itemMode === "new" && form.newLabel.trim();
  return {
    company_id: companyId,
    branch_id: form.branchId,
    title: form.title.trim(),
    customer_id: form.customerId || null,
    customer_name: form.customerId ? null : text(form.customerName),
    customer_phone: form.customerId ? null : text(form.customerPhone),
    asset_id: form.itemMode === "existing" ? form.assetId || null : null,
    new_asset: newItem ? { label: form.newLabel.trim(), kind: form.newKind.trim() || "item", identifiers: cleanIdentifiers(form.newRows) } : null,
    description: text(form.description),
    condition_notes: text(form.condition),
    assignee_id: form.assigneeId || null,
    promised_at: form.promised || null,
    checklist_items: items.length > 0 ? items : null,
    job_type_code: form.jobTypeCode || null,
    odometer_in: form.odometer.trim() || null,
    fuel_level: text(form.fuel),
    key_tag: text(form.keyTag),
    belongings: text(form.belongings),
    acknowledged_by_name: text(form.signedBy),
  };
}
