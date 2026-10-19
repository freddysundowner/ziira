import { useEffect, useState } from "react";

import { api, Button, Checkbox, Field, Input, Modal, Select, toast, today, unwrap, useMutation, useTranslation } from "@/sdk";

import { useReasons, useRefreshBookings } from "../hooks";
import { dayOf, zonedIso } from "../lib";
import type { Appointment } from "../types";
import { SlotPicker } from "./SlotPicker";

/** Move an appointment to another time (and, if wanted, another person or room). A reason from the list is required. */
export function RescheduleDialog({ appointment, open, onClose, zone, preset }: {
  appointment: Appointment; open: boolean; onClose: () => void; zone?: string; preset?: { startIso: string; resourceId?: string };
}) {
  const { t } = useTranslation("bookings");
  const reasons = useReasons("appointment_reschedule");
  const refresh = useRefreshBookings();
  const [day, setDay] = useState("");
  const [start, setStart] = useState("");
  const [resourceIds, setResourceIds] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const [manual, setManual] = useState(false);
  const [time, setTime] = useState("09:00");
  useEffect(() => {
    if (!open) return;
    setDay(dayOf(preset?.startIso ?? appointment.starts_at, zone));
    setStart(preset?.startIso ?? "");
    setResourceIds(preset?.resourceId ? [preset.resourceId] : appointment.resource_ids);
    setReason(""); setManual(false);
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const when = manual ? zonedIso(day || today(), time, zone) : start;
  const move = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/bookings/appointments/{appointment_id}/reschedule", {
      params: { path: { appointment_id: appointment.id } },
      body: { starts_at: when, reason_code_id: reason, resource_ids: resourceIds.length ? resourceIds.slice(0, 1) : null, allow_outside_hours: manual } })),
    onSuccess: () => { void refresh(); toast(t("reschedule.done"), "ok"); onClose(); },
  });

  return (
    <Modal open={open} onClose={onClose} title={t("reschedule.title", { name: appointment.client_name ?? appointment.service })} size="lg"
      footer={<><Button variant="secondary" onClick={onClose}>{t("close")}</Button><Button disabled={!when || !reason} loading={move.isPending} onClick={() => move.mutate()}>{t("reschedule.confirm")}</Button></>}>
      <div className="space-y-4">
        <Field label={t("form.date")}><Input type="date" value={day} onChange={(e) => { setDay(e.target.value); setStart(""); }} autoFocus /></Field>
        {manual ? (
          <Field label={t("form.time")}><Input type="time" value={time} onChange={(e) => setTime(e.target.value)} /></Field>
        ) : (
          day && <SlotPicker offerId={appointment.offer_id} branchId={appointment.branch_id} day={day} resourceId={resourceIds[0]} zone={zone} value={start}
            onChange={(s) => { setStart(s.startIso); setResourceIds(s.resourceIds.includes(resourceIds[0] ?? "") ? resourceIds : s.resourceIds.slice(0, 1)); }} />
        )}
        <Checkbox checked={manual} onChange={(e) => setManual(e.target.checked)} label={t("form.outsideHours")} />
        <Field label={t("reschedule.reason")} required>
          <Select value={reason} onChange={(e) => setReason(e.target.value)}>
            <option value="">{t("cancel.pickReason")}</option>
            {(reasons.data ?? []).map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
          </Select>
        </Field>
      </div>
    </Modal>
  );
}
