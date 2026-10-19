import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";

import {
  Alert, api, Button, Checkbox, Combobox, Drawer, Field, FormGrid, Input, NumberInput, Select, Textarea, toast, today, unwrap, useMutation, useTranslation,
} from "@/sdk";

import { useOffers, useRefreshBookings, useResources, useUnit } from "../hooks";
import { dayOf, zonedIso } from "../lib";
import { type PickedSlot, SlotPicker } from "./SlotPicker";

export interface BookingPreset { startIso?: string; resourceId?: string; offerId?: string }

/** Book an appointment (or a walk-in who is here now) from the front desk. */
export function BookingForm({ open, onClose, branchId, companyId, zone, preset, walkIn, onWaitlist, onBooked }: {
  open: boolean; onClose: () => void; branchId: string; companyId: string; zone?: string; preset?: BookingPreset; walkIn?: boolean;
  onWaitlist?: (offerId: string, day: string) => void; onBooked?: (id: string) => void;
}) {
  const { t } = useTranslation("bookings");
  const refresh = useRefreshBookings();
  const offers = useOffers(companyId);
  const resources = useResources(branchId);
  const hasCustomers = useUnit("crm");
  const localId = useRef(crypto.randomUUID());
  const [offerId, setOfferId] = useState("");
  const [resourceId, setResourceId] = useState("");
  const [day, setDay] = useState(today());
  const [slot, setSlot] = useState<PickedSlot | null>(null);
  const [manual, setManual] = useState(false);
  const [time, setTime] = useState("09:00");
  const [customerId, setCustomerId] = useState("");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [note, setNote] = useState("");
  const [repeat, setRepeat] = useState("");
  const [times, setTimes] = useState("4");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    localId.current = crypto.randomUUID();
    setOfferId(preset?.offerId ?? ""); setResourceId(preset?.resourceId ?? "");
    setDay(preset?.startIso ? dayOf(preset.startIso, zone) : today());
    setSlot(preset?.startIso ? { startIso: preset.startIso, resourceIds: preset.resourceId ? [preset.resourceId] : [] } : null);
    setManual(false); setCustomerId(""); setName(""); setPhone(""); setEmail(""); setNote(""); setRepeat(""); setError(null);
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const offer = offers.data?.find((o) => o.id === offerId);
  const doers = useMemo(() => (resources.data ?? []).filter((r) => offer?.resource_ids.includes(r.id)), [resources.data, offer]);
  useEffect(() => { if (!offerId && offers.data?.length === 1) setOfferId(offers.data[0]?.id ?? ""); }, [offers.data, offerId]);
  const isClass = offer?.kind === "class";
  const when = manual ? zonedIso(day, time, zone) : slot?.startIso ?? "";

  const searchCustomers = async (text: string) => {
    const rows = await unwrap(api.GET("/api/v1/crm/customers", { params: { query: { search: text || undefined, limit: 20 } } }));
    return rows.map((c) => ({ value: c.id, label: c.name, hint: c.phone ?? undefined }));
  };

  const save = useMutation({
    meta: { silent: true },
    mutationFn: async () => {
      const common = {
        offer_id: offerId, branch_id: branchId, resource_ids: resourceId ? [resourceId] : slot?.resourceIds.length === 1 ? slot.resourceIds : null,
        customer_id: customerId || null, client_name: name.trim() || null, client_phone: phone.trim() || null, note: note.trim() || null,
      };
      if (walkIn) return { id: (await unwrap(api.POST("/api/v1/bookings/appointments/walk-in", { body: { ...common, local_id: localId.current } }))).id, skipped: 0, problem: "" };
      const body = { ...common, client_email: email.trim() || null, starts_at: when, local_id: localId.current, allow_outside_hours: manual };
      if (repeat && !isClass) {
        const made = await unwrap(api.POST("/api/v1/bookings/appointments/series", { body: { ...body, frequency: repeat as "weekly", count: Number(times) || 2 } }));
        return { id: made.created[0]?.id ?? "", skipped: made.conflicts.length, problem: made.conflicts[0]?.problem ?? "" };
      }
      return { id: (await unwrap(api.POST("/api/v1/bookings/appointments", { body }))).id, skipped: 0, problem: "" };
    },
    onSuccess: (r) => {
      void refresh();
      toast(r.skipped ? t("form.seriesSkipped", { count: r.skipped, problem: r.problem }) : t(walkIn ? "form.walkInDone" : "form.done"), r.skipped ? "warn" : "ok");
      onClose();
      if (r.id) onBooked?.(r.id);
    },
    onError: (e) => setError((e as Error).message),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); setError(null); save.mutate(); };
  const ready = !!offerId && (walkIn || !!when) && (isClass || !!customerId || !!name.trim());

  return (
    <Drawer open={open} onClose={onClose} title={walkIn ? t("form.walkInTitle") : t("form.title")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("close")}</Button><Button type="submit" form="booking-form" loading={save.isPending} disabled={!ready}>{walkIn ? t("form.checkInNow") : t("form.book")}</Button></>}>
      <form id="booking-form" onSubmit={submit} className="space-y-4">
        {error && <Alert tone="bad">{error}</Alert>}
        <Field label={t("form.service")} required>
          <Select value={offerId} onChange={(e) => { setOfferId(e.target.value); setResourceId(""); setSlot(null); }} autoFocus>
            <option value="">{t("form.pickService")}</option>
            {(offers.data ?? []).map((o) => <option key={o.id} value={o.id}>{o.name} ({o.duration_minutes} {t("minutes")})</option>)}
          </Select>
        </Field>
        {offers.data?.length === 0 && <Alert tone="info">{t("form.noServices")}</Alert>}
        {offer && offer.resource_mode === "any" && doers.length > 1 && (
          <Field label={t("form.with")}>
            <Select value={resourceId} onChange={(e) => { setResourceId(e.target.value); setSlot(null); }}>
              <option value="">{t("form.anyone")}</option>
              {doers.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
            </Select>
          </Field>
        )}
        {!walkIn && offer && (
          <>
            <Field label={t("form.date")} required><Input type="date" value={day} onChange={(e) => { setDay(e.target.value); setSlot(null); }} /></Field>
            {manual
              ? <Field label={t("form.time")}><Input type="time" value={time} onChange={(e) => setTime(e.target.value)} /></Field>
              : <Field label={t("form.freeTimes")} required hint={t("form.freeTimesHint")}>
                  <SlotPicker offerId={offerId} branchId={branchId} day={day} resourceId={resourceId || undefined} zone={zone} value={slot?.startIso ?? ""} onChange={setSlot} />
                </Field>}
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Checkbox checked={manual} onChange={(e) => setManual(e.target.checked)} label={t("form.outsideHours")} />
              {onWaitlist && <Button size="sm" variant="ghost" onClick={() => onWaitlist(offerId, day)}>{t("form.joinWaitlist")}</Button>}
            </div>
          </>
        )}
        {offer && !isClass && (
          <>
            {hasCustomers && (
              <Field label={t("form.customer")} hint={t("form.customerHint")}>
                <Combobox value={customerId} clearable search={searchCustomers} placeholder={t("form.findCustomer")}
                  onChange={(v, o) => { setCustomerId(v); if (o) setName(o.label); if (o?.hint) setPhone(o.hint); }} />
              </Field>
            )}
            <FormGrid>
              <Field label={t("form.name")} required={!customerId}><Input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} /></Field>
              <Field label={t("form.phone")}><Input type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} maxLength={30} /></Field>
            </FormGrid>
            {!walkIn && <Field label={t("form.email")}><Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} maxLength={200} /></Field>}
          </>
        )}
        <Field label={t("form.note")}><Textarea value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} /></Field>
        {!walkIn && offer && !isClass && (
          <FormGrid>
            <Field label={t("form.repeat")}>
              <Select value={repeat} onChange={(e) => setRepeat(e.target.value)}>
                <option value="">{t("form.noRepeat")}</option>
                {(["weekly", "biweekly", "monthly"] as const).map((f) => <option key={f} value={f}>{t(`form.repeats.${f}`)}</option>)}
              </Select>
            </Field>
            {repeat && <Field label={t("form.times")} hint={t("form.timesHint")}><NumberInput value={times} onChange={(v) => setTimes(v.split(".")[0] ?? "")} /></Field>}
          </FormGrid>
        )}
      </form>
    </Drawer>
  );
}
