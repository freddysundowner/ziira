import { Plus } from "lucide-react";
import { useState } from "react";

import { api, Button, Field, FormGrid, Input, Modal, NumberInput, Select, unwrap, useTranslation } from "@/sdk";

import { useJobAction } from "../hooks";
import type { Job } from "../types";
import { LinesTable } from "./LinesTable";

const KINDS = ["towing", "courtesy_car", "storage", "other"] as const;

/** Towing, a courtesy car, storage and other agreed fees: charges that are neither parts nor labour. */
export function ChargesCard({ job, currency, editable }: { job: Job; currency: string | undefined; editable: boolean }) {
  const { t } = useTranslation("jobs");
  const [adding, setAdding] = useState(false);
  const remove = useJobAction(job.id, (id: string) => unwrap(api.DELETE("/api/v1/jobs/jobs/{job_id}/charges/{charge_id}", { params: { path: { job_id: job.id, charge_id: id } } })), { done: t("garage.charges.removed") });
  if (job.charges.length === 0 && !editable) return null;
  return (
    <>
      <LinesTable title={t("garage.charges.title")} currency={currency} showCost={false} empty={t("garage.charges.empty")} qtyLabel={t("lines.quantity")} unitLabel={t("lines.price")}
        action={editable && <Button size="sm" variant="secondary" onClick={() => setAdding(true)}><Plus className="h-4 w-4" />{t("garage.charges.add")}</Button>}
        canRemove={editable} onRemove={(id) => remove.mutate(id)}
        lines={job.charges.map((c) => ({ id: c.id, description: c.description, detail: t(`garage.charges.kind.${c.kind}`), quantity: c.quantity, unit: c.unit_price, total: c.total, voided: c.voided }))} />
      <AddChargeDialog jobId={job.id} open={adding} onClose={() => setAdding(false)} currency={currency} />
    </>
  );
}

function AddChargeDialog({ jobId, open, onClose, currency }: { jobId: string; open: boolean; onClose: () => void; currency: string | undefined }) {
  const { t } = useTranslation("jobs");
  const [kind, setKind] = useState<(typeof KINDS)[number]>("towing");
  const [description, setDescription] = useState("");
  const [price, setPrice] = useState("");
  const [qty, setQty] = useState("1");
  const add = useJobAction(jobId, () => unwrap(api.POST("/api/v1/jobs/jobs/{job_id}/charges", { params: { path: { job_id: jobId } }, body: {
    kind, description: description.trim() || t(`garage.charges.kind.${kind}`), unit_price: price, quantity: qty } })),
  { done: t("garage.charges.added"), onDone: () => { setDescription(""); setPrice(""); setQty("1"); onClose(); } });
  return (
    <Modal open={open} onClose={onClose} title={t("garage.charges.add")} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button loading={add.isPending} disabled={price === "" || !(Number(qty) > 0)} onClick={() => add.mutate(undefined)}>{t("garage.charges.add")}</Button></>}>
      <div className="space-y-4">
        <Field label={t("garage.charges.kindLabel")}>
          <Select value={kind} onChange={(e) => setKind(e.target.value as (typeof KINDS)[number])}>{KINDS.map((k) => <option key={k} value={k}>{t(`garage.charges.kind.${k}`)}</option>)}</Select>
        </Field>
        <Field label={t("lines.description")}><Input maxLength={300} value={description} placeholder={t(`garage.charges.kind.${kind}`)} onChange={(e) => setDescription(e.target.value)} /></Field>
        <FormGrid>
          <Field label={t("lines.quantity")} required><NumberInput value={qty} onChange={setQty} /></Field>
          <Field label={t("lines.price")} required hint={currency ? t("parts.priceHint", { currency }) : undefined}><NumberInput value={price} onChange={setPrice} /></Field>
        </FormGrid>
      </div>
    </Modal>
  );
}
