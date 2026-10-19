import { Clock, PackageCheck, Plus, Timer, Undo2, Truck } from "lucide-react";
import { useState } from "react";

import { api, Badge, Button, formatDate, Modal, Field, Input, NumberInput, unwrap, useCan, useTranslation } from "@/sdk";

import { useJobAction } from "../hooks";
import { showsCost } from "../lib";
import type { Job, Part } from "../types";
import { AddLabourDialog } from "./AddLabourDialog";
import { AddPartDialog } from "./AddPartDialog";
import { ChargesCard } from "./ChargesCard";
import { LinesTable } from "./LinesTable";

/** Parts used and hours worked. A removed line goes back (stock returns to the shelf) and stays visible, struck through. */
export function PartsTab({ job, currency, editable }: { job: Job; currency: string | undefined; editable: boolean }) {
  const { t } = useTranslation("jobs");
  const canParts = useCan("jobs.parts") && editable;
  const canLabour = useCan("jobs.manage") && editable;
  const [adding, setAdding] = useState(false);
  const [timing, setTiming] = useState(false);
  const [ordering, setOrdering] = useState<Part | null>(null);
  const [returning, setReturning] = useState<Part | null>(null);
  const [booking, setBooking] = useState<{ id: string; hours: string; description: string } | null>(null);
  const removePart = useJobAction(job.id, (id: string) => unwrap(api.DELETE("/api/v1/jobs/jobs/{job_id}/parts/{part_id}", { params: { path: { job_id: job.id, part_id: id } } })), { done: t("parts.removed") });
  const removeLabour = useJobAction(job.id, (id: string) => unwrap(api.DELETE("/api/v1/jobs/jobs/{job_id}/labour/{line_id}", { params: { path: { job_id: job.id, line_id: id } } })), { done: t("labour.removed") });
  const arrived = useJobAction(job.id, (id: string) => unwrap(api.POST("/api/v1/jobs/jobs/{job_id}/parts/{part_id}/arrived", { params: { path: { job_id: job.id, part_id: id } }, body: {} })), { done: t("garage.parts.arrivedDone") });
  const cost = showsCost(job);
  const partBadges = (p: Part) => (
    <>
      {p.part_class && <Badge tone="neutral">{t(`garage.parts.classes.${p.part_class}`)}</Badge>}
      {p.source === "customer_supplied" && <Badge tone="info">{t("garage.parts.fromCustomer")}</Badge>}
      {p.source === "special_order" && p.order_status && <Badge tone={p.order_status === "arrived" ? "ok" : "warn"}>{t(`garage.parts.order.${p.order_status}`)}</Badge>}
      {p.keep_old_part && <Badge tone="neutral">{t("garage.parts.keepOldBadge")}</Badge>}
    </>
  );
  const partDetail = (p: Part) => [
    p.is_stock ? t("parts.fromStock") : undefined, p.supplier_name,
    p.purchase_order_number ? t("garage.parts.orderRef", { number: p.purchase_order_number }) : undefined,
    p.expected_on && p.order_status !== "arrived" ? t("garage.parts.expectedOn", { date: formatDate(p.expected_on) }) : undefined,
    p.void_reason ?? undefined,
  ].filter(Boolean).join(" · ") || undefined;
  const partActions = (p: Part) => !canParts ? undefined : (
    <>
      {p.source === "special_order" && p.order_status !== "arrived" && (
        <>
          <Button size="sm" variant="secondary" onClick={() => setOrdering(p)}><Truck className="h-3.5 w-3.5" />{t("garage.parts.markOrdered")}</Button>
          <Button size="sm" variant="secondary" loading={arrived.isPending} onClick={() => arrived.mutate(p.id)}><PackageCheck className="h-3.5 w-3.5" />{t("garage.parts.markArrived")}</Button>
        </>
      )}
      {p.source !== "customer_supplied" && <Button size="sm" variant="ghost" onClick={() => setReturning(p)}><Undo2 className="h-3.5 w-3.5" />{t("garage.parts.returnSome")}</Button>}
    </>
  );
  return (
    <div className="space-y-4">
      <LinesTable title={t("parts.title")} currency={currency} showCost={cost} empty={t("parts.empty")} qtyLabel={t("lines.quantity")} unitLabel={t("lines.price")}
        action={canParts && <Button size="sm" onClick={() => setAdding(true)}><Plus className="h-4 w-4" />{t("parts.add")}</Button>}
        canRemove={canParts} onRemove={(id) => removePart.mutate(id)}
        lines={job.parts.map((p) => ({ id: p.id, description: p.description, detail: partDetail(p), quantity: p.quantity, unit: p.unit_price, total: p.total, cost: p.cost_value, voided: p.voided, badges: partBadges(p), actions: partActions(p) }))} />
      <LinesTable title={t("labour.title")} currency={currency} showCost={false} empty={t("labour.empty")} qtyLabel={t("labour.hours")} unitLabel={t("labour.rateColumn")}
        action={canLabour && <Button size="sm" onClick={() => setTiming(true)}><Clock className="h-4 w-4" />{t("labour.addMine")}</Button>}
        canRemove={canLabour} onRemove={(id) => removeLabour.mutate(id)}
        lines={job.labour.map((l) => ({
          id: l.id, description: l.description, quantity: l.hours, unit: l.rate, total: l.total, voided: l.voided,
          detail: [l.assignee_name, formatDate(l.work_date), l.work_type_code, l.flat_price ? t("garage.labour.fixedPrice") : undefined,
            l.booked_hours != null ? t("garage.labour.bookedText", { hours: Number(l.booked_hours) }) : undefined].filter(Boolean).join(" · "),
          actions: canLabour ? <Button size="sm" variant="ghost" onClick={() => setBooking({ id: l.id, hours: l.booked_hours ?? "", description: l.description })}><Timer className="h-3.5 w-3.5" />{t("garage.labour.setBooked")}</Button> : undefined,
        }))} />
      <ChargesCard job={job} currency={currency} editable={canLabour} />
      <AddPartDialog jobId={job.id} companyId={job.company_id} open={adding} onClose={() => setAdding(false)} currency={currency} />
      <AddLabourDialog jobId={job.id} companyId={job.company_id} open={timing} onClose={() => setTiming(false)} currency={currency} />
      <OrderedDialog jobId={job.id} part={ordering} onClose={() => setOrdering(null)} />
      <ReturnDialog jobId={job.id} part={returning} onClose={() => setReturning(null)} />
      <BookedDialog jobId={job.id} line={booking} onClose={() => setBooking(null)} />
    </div>
  );
}

/** A part for the job was ordered from a supplier: who, when it should come, and the purchase order if there is one. */
function OrderedDialog({ jobId, part, onClose }: { jobId: string; part: Part | null; onClose: () => void }) {
  const { t } = useTranslation("jobs");
  const [supplier, setSupplier] = useState("");
  const [expected, setExpected] = useState("");
  const [order, setOrder] = useState("");
  const save = useJobAction(jobId, () => unwrap(api.POST("/api/v1/jobs/jobs/{job_id}/parts/{part_id}/ordered", { params: { path: { job_id: jobId, part_id: part?.id ?? "" } }, body: {
    supplier_name: supplier.trim() || part?.supplier_name || null, expected_on: expected || part?.expected_on || null, purchase_order_number: order.trim() || null } })),
  { done: t("garage.parts.orderedDone"), onDone: onClose });
  return (
    <Modal open={part !== null} onClose={onClose} title={t("garage.parts.markOrdered")} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button loading={save.isPending} onClick={() => save.mutate(undefined)}>{t("common.save")}</Button></>}>
      <div className="space-y-4">
        <p className="text-sm text-muted">{part?.description}</p>
        <Field label={t("garage.parts.supplier")}><Input maxLength={160} defaultValue={part?.supplier_name ?? ""} onChange={(e) => setSupplier(e.target.value)} /></Field>
        <Field label={t("garage.parts.expected")}><Input type="date" defaultValue={part?.expected_on ?? ""} onChange={(e) => setExpected(e.target.value)} /></Field>
        <Field label={t("garage.parts.orderNumber")} hint={t("garage.parts.orderNumberHint")}><Input maxLength={40} onChange={(e) => setOrder(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}

/** Some of a part was not used: put that quantity back (stock goes back on the shelf). */
function ReturnDialog({ jobId, part, onClose }: { jobId: string; part: Part | null; onClose: () => void }) {
  const { t } = useTranslation("jobs");
  const [qty, setQty] = useState("1");
  const [reason, setReason] = useState("");
  const save = useJobAction(jobId, () => unwrap(api.POST("/api/v1/jobs/jobs/{job_id}/parts/{part_id}/return", { params: { path: { job_id: jobId, part_id: part?.id ?? "" } }, body: { quantity: qty, reason: reason.trim() || null } })),
    { done: t("garage.parts.returnedDone"), onDone: () => { setQty("1"); setReason(""); onClose(); } });
  return (
    <Modal open={part !== null} onClose={onClose} title={t("garage.parts.returnSome")} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button loading={save.isPending} disabled={!(Number(qty) > 0)} onClick={() => save.mutate(undefined)}>{t("garage.parts.returnConfirm")}</Button></>}>
      <div className="space-y-4">
        <p className="text-sm text-muted">{t("garage.parts.returnHint", { name: part?.description ?? "", qty: Number(part?.quantity ?? 0) })}</p>
        <Field label={t("garage.parts.returnQty")} required><NumberInput value={qty} onChange={setQty} /></Field>
        <Field label={t("garage.parts.returnReason")}><Input maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}

/** How long the technician really worked on a labour line (what the customer is billed stays as quoted). */
function BookedDialog({ jobId, line, onClose }: { jobId: string; line: { id: string; hours: string; description: string } | null; onClose: () => void }) {
  const { t } = useTranslation("jobs");
  const [hours, setHours] = useState("");
  const save = useJobAction(jobId, () => unwrap(api.POST("/api/v1/jobs/jobs/{job_id}/labour/{line_id}/booked", { params: { path: { job_id: jobId, line_id: line?.id ?? "" } }, body: { booked_hours: hours || line?.hours || "0" } })),
    { done: t("garage.labour.bookedDone"), onDone: () => { setHours(""); onClose(); } });
  return (
    <Modal open={line !== null} onClose={onClose} title={t("garage.labour.setBooked")} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button loading={save.isPending} onClick={() => save.mutate(undefined)}>{t("common.save")}</Button></>}>
      <div className="space-y-4">
        <p className="text-sm text-muted">{line?.description}</p>
        <Field label={t("garage.labour.booked")} hint={t("garage.labour.bookedHint")}><NumberInput value={hours || line?.hours || ""} onChange={setHours} /></Field>
      </div>
    </Modal>
  );
}
