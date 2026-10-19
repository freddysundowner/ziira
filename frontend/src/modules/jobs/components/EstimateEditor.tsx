import { Plus, X } from "lucide-react";
import { useEffect, useState } from "react";

import { api, Button, Drawer, Field, IconButton, Input, NumberInput, Select, Textarea, unwrap, useTranslation } from "@/sdk";

import { blankLine, type EditLine, linesOf, linesReady, toLineBodies } from "../estimateForm";
import { useEstimateAction } from "../hooks";
import type { Estimate } from "../types";
import { ProductPicker } from "./pickers";

/** Write or change the lines of a draft estimate. Prices include tax; a blank price takes the item's usual price or the labour rate. */
export function EstimateEditor({ jobId, estimate, open, onClose, currency }: { jobId: string; estimate: Estimate | null; open: boolean; onClose: () => void; currency: string | undefined }) {
  const { t } = useTranslation("jobs");
  const [lines, setLines] = useState<EditLine[]>([blankLine()]);
  const [notes, setNotes] = useState("");
  const [validUntil, setValidUntil] = useState("");
  useEffect(() => {
    if (!open) return;
    setLines(estimate ? linesOf(estimate) : [blankLine()]);
    setNotes(estimate?.notes ?? "");
    setValidUntil(estimate?.valid_until ?? "");
  }, [open, estimate]);
  const set = (i: number, patch: Partial<EditLine>) => setLines((all) => all.map((l, at) => (at === i ? { ...l, ...patch } : l)));
  const save = useEstimateAction(() => estimate
    ? unwrap(api.PATCH("/api/v1/jobs/estimates/{estimate_id}", { params: { path: { estimate_id: estimate.id } }, body: { lines: toLineBodies(lines), notes: notes.trim() || null, valid_until: validUntil || null } }))
    : unwrap(api.POST("/api/v1/jobs/jobs/{job_id}/estimates", { params: { path: { job_id: jobId } }, body: { lines: toLineBodies(lines), from_job: false, kind: "main", notes: notes.trim() || null, valid_until: validUntil || null } })),
  { done: t("estimates.saved"), onDone: onClose });
  return (
    <Drawer open={open} onClose={onClose} title={estimate ? t("estimates.editTitle", { version: estimate.version }) : t("estimates.newTitle")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button loading={save.isPending} disabled={!linesReady(lines)} onClick={() => save.mutate(undefined)}>{t("common.save")}</Button></>}>
      <div className="space-y-4">
        <p className="text-sm text-muted">{t("estimates.editHint", { currency: currency ?? "" })}</p>
        {lines.map((line, i) => (
          <fieldset key={i} className="space-y-3 rounded-xl border border-line p-3">
            <legend className="sr-only">{t("estimates.line", { n: i + 1 })}</legend>
            <div className="flex items-center gap-2">
              <Select aria-label={t("estimates.kind")} className="w-auto" value={line.kind} onChange={(e) => set(i, { kind: e.target.value as EditLine["kind"] })}>
                {(["part", "labour", "other"] as const).map((k) => <option key={k} value={k}>{t(`estimates.kinds.${k}`)}</option>)}
              </Select>
              <span className="flex-1" />
              {lines.length > 1 && <IconButton label={t("common.remove")} onClick={() => setLines((all) => all.filter((_, at) => at !== i))}><X className="h-4 w-4" /></IconButton>}
            </div>
            {line.kind === "part" && <ProductPicker value={line.productId} onChange={(id) => set(i, { productId: id })} />}
            <Input aria-label={t("lines.description")} placeholder={line.kind === "part" && line.productId ? t("estimates.descriptionOptional") : t("lines.description")} maxLength={300} value={line.description} onChange={(e) => set(i, { description: e.target.value })} />
            <div className="grid grid-cols-2 gap-3">
              <Field label={line.kind === "labour" ? t("labour.hours") : t("lines.quantity")}><NumberInput value={line.quantity} onChange={(v) => set(i, { quantity: v })} /></Field>
              <Field label={t("lines.price")}><NumberInput value={line.unitPrice} placeholder={t("estimates.priceDefault")} onChange={(v) => set(i, { unitPrice: v })} /></Field>
            </div>
          </fieldset>
        ))}
        <Button variant="secondary" size="sm" onClick={() => setLines((all) => [...all, blankLine()])}><Plus className="h-4 w-4" />{t("estimates.addLine")}</Button>
        <Field label={t("estimates.notes")} hint={t("estimates.notesHint")}><Textarea maxLength={1000} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
        <Field label={t("estimates.validUntil")} hint={t("estimates.validUntilHint")}><Input type="date" value={validUntil} onChange={(e) => setValidUntil(e.target.value)} /></Field>
      </div>
    </Drawer>
  );
}
