import { CalendarClock, Car, HandCoins, Plus } from "lucide-react";
import { useState } from "react";

import { api, Badge, Button, Card, Combobox, DetailList, Field, FormGrid, formatDate, Input, Modal, money, NumberInput, Select, Textarea, unwrap, useCan, useTranslation } from "@/sdk";

import { useBays, useJobAction, searchCourtesyCars } from "../hooks";
import type { Job } from "../types";

/** The workshop side of a job: what was noted at drop-off, the bay, a courtesy car, a deposit and storage. */
export function WorkshopTab({ job, currency, editable }: { job: Job; currency: string | undefined; editable: boolean }) {
  return (
    <div className="space-y-4">
      <IntakeCard job={job} editable={editable} />
      <BayCard job={job} editable={editable} />
      <LoanCard job={job} editable={editable} />
      <DepositCard job={job} currency={currency} />
      <StorageCard job={job} currency={currency} editable={editable} />
    </div>
  );
}

const ISO = (local: string): string => new Date(local).toISOString();

/** Odometer, fuel, key tag, belongings and who signed for the drop-off, and when the item is next due for service. */
function IntakeCard({ job, editable }: { job: Job; editable: boolean }) {
  const { t } = useTranslation("jobs");
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ odometer_in: "", odometer_out: "", fuel_level: "", key_tag: "", belongings: "", acknowledged_by_name: "", next_service_date: "", next_service_odometer: "" });
  const open = () => {
    const num = (v: string | null | undefined): string => (v ? String(Number(v)) : "");
    setForm({ odometer_in: num(job.odometer_in), odometer_out: num(job.odometer_out), fuel_level: job.fuel_level ?? "", key_tag: job.key_tag ?? "", belongings: job.belongings ?? "",
      acknowledged_by_name: job.acknowledged_by_name ?? "", next_service_date: job.asset_detail?.next_service_date ?? "", next_service_odometer: num(job.asset_detail?.next_service_odometer) });
    setEditing(true);
  };
  // An invoiced job is locked: only the item's next service can still change.
  const nextService = job.asset ? { next_service_date: form.next_service_date || null, next_service_odometer: form.next_service_odometer || null } : {};
  const save = useJobAction(job.id, () => unwrap(api.PATCH("/api/v1/jobs/jobs/{job_id}", { params: { path: { job_id: job.id } }, body: job.locked ? nextService : {
    odometer_in: form.odometer_in || null, odometer_out: form.odometer_out || null, fuel_level: form.fuel_level || null, key_tag: form.key_tag || null,
    belongings: form.belongings || null, acknowledged_by_name: form.acknowledged_by_name || null, ...nextService } })),
  { done: t("garage.workshop.saved"), onDone: () => setEditing(false) });
  const set = (k: keyof typeof form, v: string) => setForm((f) => ({ ...f, [k]: v }));
  const unit = "";
  const asset = job.asset_detail;
  const none = <span className="text-muted">—</span>;
  return (
    <Card title={t("garage.workshop.intake")} actions={editable || job.locked ? <Button size="sm" variant="secondary" onClick={open}>{t("actions.edit")}</Button> : undefined}>
      <DetailList items={[
        { label: t("garage.workshop.odometerIn"), value: job.odometer_in ? `${Number(job.odometer_in)}${unit}` : none },
        { label: t("garage.workshop.odometerOut"), value: job.odometer_out ? Number(job.odometer_out) : none },
        { label: t("garage.workshop.fuel"), value: job.fuel_level ?? none },
        { label: t("garage.workshop.keyTag"), value: job.key_tag ?? none },
        { label: t("garage.workshop.belongings"), value: job.belongings ? <span className="whitespace-pre-line">{job.belongings}</span> : none },
        { label: t("garage.workshop.signedBy"), value: job.acknowledged_by_name ? `${job.acknowledged_by_name} · ${formatDate(job.acknowledged_at, true)}` : none },
        ...(asset ? [{ label: t("garage.workshop.nextService"), value: asset.next_service_date || asset.next_service_odometer
          ? [asset.next_service_date ? formatDate(asset.next_service_date) : null, asset.next_service_odometer ? `${Number(asset.next_service_odometer)}` : null].filter(Boolean).join(" · ") : none }] : []),
      ]} />
      <Modal open={editing} onClose={() => setEditing(false)} title={t("garage.workshop.intake")}
        footer={<><Button variant="secondary" onClick={() => setEditing(false)}>{t("common.cancel")}</Button><Button loading={save.isPending} onClick={() => save.mutate(undefined)}>{t("common.save")}</Button></>}>
        <div className="space-y-4">
          {!job.locked && <>
          <FormGrid>
            <Field label={t("garage.workshop.odometerIn")}><NumberInput value={form.odometer_in} onChange={(v) => set("odometer_in", v)} /></Field>
            <Field label={t("garage.workshop.odometerOut")}><NumberInput value={form.odometer_out} onChange={(v) => set("odometer_out", v)} /></Field>
            <Field label={t("garage.workshop.fuel")}><Input maxLength={40} value={form.fuel_level} onChange={(e) => set("fuel_level", e.target.value)} /></Field>
            <Field label={t("garage.workshop.keyTag")}><Input maxLength={40} value={form.key_tag} onChange={(e) => set("key_tag", e.target.value)} /></Field>
          </FormGrid>
          <Field label={t("garage.workshop.belongings")}><Textarea maxLength={1000} value={form.belongings} onChange={(e) => set("belongings", e.target.value)} /></Field>
          <Field label={t("garage.workshop.signedBy")} hint={t("garage.workshop.signedByHint")}><Input maxLength={160} value={form.acknowledged_by_name} onChange={(e) => set("acknowledged_by_name", e.target.value)} /></Field>
          </>}
          {job.asset && (
            <FormGrid>
              <Field label={t("garage.workshop.nextServiceDate")}><Input type="date" value={form.next_service_date} onChange={(e) => set("next_service_date", e.target.value)} /></Field>
              <Field label={t("garage.workshop.nextServiceOdometer")}><NumberInput value={form.next_service_odometer} onChange={(v) => set("next_service_odometer", v)} /></Field>
            </FormGrid>
          )}
        </div>
      </Modal>
    </Card>
  );
}

/** Schedule the job into a bay for a time; a bay holds one job at a time. */
function BayCard({ job, editable }: { job: Job; editable: boolean }) {
  const { t } = useTranslation("jobs");
  const bays = useBays(job.company_id, job.branch_id);
  const [adding, setAdding] = useState(false);
  const [bay, setBay] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const book = useJobAction(job.id, () => unwrap(api.POST("/api/v1/jobs/jobs/{job_id}/bay-bookings", { params: { path: { job_id: job.id } }, body: { bay_id: bay, starts_at: ISO(from), ends_at: ISO(to), note: null } })),
    { done: t("garage.bays.booked"), onDone: () => setAdding(false) });
  const cancel = useJobAction(job.id, (id: string) => unwrap(api.DELETE("/api/v1/jobs/bay-bookings/{booking_id}", { params: { path: { booking_id: id } } })), { done: t("garage.bays.cancelled") });
  if ((bays.data ?? []).length === 0 && job.bay_bookings.length === 0) return null;
  return (
    <Card title={t("garage.bays.title")} actions={editable && <Button size="sm" variant="secondary" onClick={() => { setBay(bays.data?.[0]?.id ?? ""); setAdding(true); }}><CalendarClock className="h-4 w-4" />{t("garage.bays.book")}</Button>}>
      {job.bay_bookings.length === 0 ? <p className="text-sm text-muted">{t("garage.bays.none")}</p> : (
        <ul className="divide-y divide-line text-sm">
          {job.bay_bookings.map((b) => (
            <li key={b.id} className="flex items-center justify-between gap-3 py-2">
              <span><span className="font-medium">{b.bay_name}</span> · {formatDate(b.starts_at, true)} → {formatDate(b.ends_at, true)}</span>
              {editable && <Button size="sm" variant="ghost" onClick={() => cancel.mutate(b.id)}>{t("garage.bays.cancel")}</Button>}
            </li>
          ))}
        </ul>
      )}
      <Modal open={adding} onClose={() => setAdding(false)} title={t("garage.bays.book")} size="sm"
        footer={<><Button variant="secondary" onClick={() => setAdding(false)}>{t("common.cancel")}</Button><Button loading={book.isPending} disabled={!bay || !from || !to} onClick={() => book.mutate(undefined)}>{t("garage.bays.book")}</Button></>}>
        <div className="space-y-4">
          <Field label={t("garage.bays.bay")}><Select value={bay} onChange={(e) => setBay(e.target.value)}>{(bays.data ?? []).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</Select></Field>
          <Field label={t("garage.bays.from")}><Input type="datetime-local" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
          <Field label={t("garage.bays.to")}><Input type="datetime-local" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
        </div>
      </Modal>
    </Card>
  );
}

/** A courtesy or hire car lent while the customer's is in the workshop: out and in dates, nothing more. */
function LoanCard({ job, editable }: { job: Job; editable: boolean }) {
  const { t } = useTranslation("jobs");
  const [adding, setAdding] = useState(false);
  const [car, setCar] = useState("");
  const [due, setDue] = useState("");
  const [odo, setOdo] = useState("");
  const [fuel, setFuel] = useState("");
  const [back, setBack] = useState<{ id: string; odo: string; fuel: string } | null>(null);
  const lend = useJobAction(job.id, () => unwrap(api.POST("/api/v1/jobs/jobs/{job_id}/loans", { params: { path: { job_id: job.id } }, body: {
    asset_id: car, due_at: due || null, odometer_out: odo || null, fuel_out: fuel || null, borrower_name: null, note: null } })), { done: t("garage.loan.lent"), onDone: () => setAdding(false) });
  const ret = useJobAction(job.id, () => unwrap(api.POST("/api/v1/jobs/loans/{loan_id}/return", { params: { path: { loan_id: back?.id ?? "" } }, body: { odometer_in: back?.odo || null, fuel_in: back?.fuel || null, note: null } })),
    { done: t("garage.loan.returned"), onDone: () => setBack(null) });
  if (job.loans.length === 0 && !editable) return null;
  return (
    <Card title={t("garage.loan.title")} actions={editable && <Button size="sm" variant="secondary" onClick={() => setAdding(true)}><Car className="h-4 w-4" />{t("garage.loan.lend")}</Button>}>
      {job.loans.length === 0 ? <p className="text-sm text-muted">{t("garage.loan.none")}</p> : (
        <ul className="divide-y divide-line text-sm">
          {job.loans.map((l) => (
            <li key={l.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <span>
                <span className="font-medium">{l.asset_label}</span> · {formatDate(l.out_at, true)}{l.due_at ? ` → ${formatDate(l.due_at)}` : ""}
                {l.in_at ? <Badge tone="ok" className="ml-2">{t("garage.loan.back", { date: formatDate(l.in_at, true) })}</Badge> : l.overdue ? <Badge tone="warn" className="ml-2">{t("garage.loan.overdue")}</Badge> : <Badge tone="info" className="ml-2">{t("garage.loan.out")}</Badge>}
              </span>
              {!l.in_at && editable && <Button size="sm" variant="secondary" onClick={() => setBack({ id: l.id, odo: "", fuel: "" })}>{t("garage.loan.markBack")}</Button>}
            </li>
          ))}
        </ul>
      )}
      <Modal open={adding} onClose={() => setAdding(false)} title={t("garage.loan.lend")} size="sm"
        footer={<><Button variant="secondary" onClick={() => setAdding(false)}>{t("common.cancel")}</Button><Button loading={lend.isPending} disabled={!car} onClick={() => lend.mutate(undefined)}>{t("garage.loan.lend")}</Button></>}>
        <div className="space-y-4">
          <p className="text-sm text-muted">{t("garage.loan.hint")}</p>
          <Field label={t("garage.loan.car")} required><Combobox value={car} onChange={setCar} search={searchCourtesyCars} placeholder={t("garage.loan.pickCar")} clearable /></Field>
          <FormGrid>
            <Field label={t("garage.loan.due")}><Input type="date" value={due} onChange={(e) => setDue(e.target.value)} /></Field>
            <Field label={t("garage.loan.odometerOut")}><NumberInput value={odo} onChange={setOdo} /></Field>
            <Field label={t("garage.workshop.fuel")}><Input maxLength={40} value={fuel} onChange={(e) => setFuel(e.target.value)} /></Field>
          </FormGrid>
        </div>
      </Modal>
      <Modal open={back !== null} onClose={() => setBack(null)} title={t("garage.loan.markBack")} size="sm"
        footer={<><Button variant="secondary" onClick={() => setBack(null)}>{t("common.cancel")}</Button><Button loading={ret.isPending} onClick={() => ret.mutate(undefined)}>{t("garage.loan.markBack")}</Button></>}>
        <FormGrid>
          <Field label={t("garage.loan.odometerIn")}><NumberInput value={back?.odo ?? ""} onChange={(v) => setBack((b) => (b ? { ...b, odo: v } : b))} /></Field>
          <Field label={t("garage.workshop.fuel")}><Input maxLength={40} value={back?.fuel ?? ""} onChange={(e) => setBack((b) => (b ? { ...b, fuel: e.target.value } : b))} /></Field>
        </FormGrid>
      </Modal>
    </Card>
  );
}

/** Money taken in advance on an order (a tailor's deposit, a deposit on a special-order part). */
function DepositCard({ job, currency }: { job: Job; currency: string | undefined }) {
  const { t } = useTranslation("jobs");
  const canTake = useCan("jobs.manage") && !job.invoiced && !job.locked;
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState<"cash" | "mobile_money" | "card" | "bank">("cash");
  const [reference, setReference] = useState("");
  const take = useJobAction(job.id, () => unwrap(api.POST("/api/v1/jobs/jobs/{job_id}/deposit", { params: { path: { job_id: job.id } }, body: { amount, method, reference: reference.trim() || null, payment_account_id: null, note: null } })),
    { done: t("garage.deposit.taken"), onDone: () => { setOpen(false); setAmount(""); setReference(""); } });
  if (!canTake && !job.deposit_amount) return null;
  return (
    <Card title={t("garage.deposit.title")} actions={canTake && <Button size="sm" variant="secondary" onClick={() => setOpen(true)}><HandCoins className="h-4 w-4" />{t("garage.deposit.take")}</Button>}>
      <p className="text-sm">{job.deposit_amount ? t("garage.deposit.received", { amount: money(job.deposit_amount, currency), date: formatDate(job.deposit_at, true) }) : <span className="text-muted">{t("garage.deposit.none")}</span>}</p>
      <p className="mt-1 text-xs text-muted">{t("garage.deposit.hint")}</p>
      <Modal open={open} onClose={() => setOpen(false)} title={t("garage.deposit.take")} size="sm"
        footer={<><Button variant="secondary" onClick={() => setOpen(false)}>{t("common.cancel")}</Button><Button loading={take.isPending} disabled={!(Number(amount) > 0)} onClick={() => take.mutate(undefined)}>{t("garage.deposit.take")}</Button></>}>
        <div className="space-y-4">
          <Field label={t("garage.deposit.amount")} required><NumberInput value={amount} onChange={setAmount} autoFocus /></Field>
          <Field label={t("garage.deposit.method")}>
            <Select value={method} onChange={(e) => setMethod(e.target.value as typeof method)}>{(["cash", "mobile_money", "card", "bank"] as const).map((m) => <option key={m} value={m}>{t(`garage.deposit.methods.${m}`)}</option>)}</Select>
          </Field>
          {method !== "cash" && <Field label={t("garage.deposit.reference")}><Input maxLength={60} value={reference} onChange={(e) => setReference(e.target.value)} /></Field>}
        </div>
      </Modal>
    </Card>
  );
}

/** Storage after the item was ready: the fee so far, charge it, or waive it. */
function StorageCard({ job, currency, editable }: { job: Job; currency: string | undefined; editable: boolean }) {
  const { t } = useTranslation("jobs");
  const charge = useJobAction(job.id, () => unwrap(api.POST("/api/v1/jobs/jobs/{job_id}/storage-fee", { params: { path: { job_id: job.id } } })), { done: t("garage.storage.charged") });
  const waive = useJobAction(job.id, () => unwrap(api.POST("/api/v1/jobs/jobs/{job_id}/storage-fee/waive", { params: { path: { job_id: job.id }, query: { waived: !job.storage_fee_waived } } })), { done: t("garage.storage.waivedDone") });
  if (job.storage_days === 0 && !job.storage_fee_waived) return null;
  return (
    <Card title={t("garage.storage.title")}>
      <p className="text-sm">{job.storage_fee_waived ? t("garage.storage.waived") : t("garage.storage.owed", { days: job.storage_days, fee: money(job.storage_fee, currency) })}</p>
      {editable && (
        <div className="mt-3 flex gap-2">
          {!job.storage_fee_waived && Number(job.storage_fee) > 0 && <Button size="sm" variant="secondary" loading={charge.isPending} onClick={() => charge.mutate(undefined)}><Plus className="h-4 w-4" />{t("garage.storage.charge")}</Button>}
          <Button size="sm" variant="ghost" loading={waive.isPending} onClick={() => waive.mutate(undefined)}>{job.storage_fee_waived ? t("garage.storage.unwaive") : t("garage.storage.waive")}</Button>
        </div>
      )}
    </Card>
  );
}
