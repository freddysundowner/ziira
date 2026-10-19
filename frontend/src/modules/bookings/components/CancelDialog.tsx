import { useEffect, useState } from "react";

import { api, Button, Field, Input, Modal, Select, toast, unwrap, useMutation, useTranslation } from "@/sdk";

import { useReasons, useRefreshBookings } from "../hooks";
import type { Appointment } from "../types";

/** Cancel an appointment: a reason from the list is required. Says if the cancellation is late. */
export function CancelDialog({ appointment, open, onClose, onDone }: { appointment: Appointment; open: boolean; onClose: () => void; onDone?: (a: Appointment) => void }) {
  const { t } = useTranslation("bookings");
  const reasons = useReasons("appointment_cancel");
  const refresh = useRefreshBookings();
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  useEffect(() => { if (open) { setReason(""); setNote(""); } }, [open]);
  const options = (reasons.data ?? []).filter((r) => r.code !== "NO_SHOW");
  const needsNote = options.find((r) => r.id === reason)?.requires_note ?? false;

  const cancel = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/bookings/appointments/{appointment_id}/cancel", {
      params: { path: { appointment_id: appointment.id } }, body: { reason_code_id: reason, note: note.trim() || null } })),
    onSuccess: (a) => {
      void refresh();
      toast(a.late_cancellation ? t("cancel.doneLate") : t("cancel.done"), "ok");
      if (a.waitlist_matches > 0) toast(t("cancel.waitlistMatches", { count: a.waitlist_matches }), "info");
      onClose();
      onDone?.(a);
    },
  });

  return (
    <Modal open={open} onClose={onClose} title={t("cancel.title", { name: appointment.client_name ?? appointment.service })}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel.keep")}</Button><Button variant="danger" disabled={!reason || (needsNote && !note.trim())} loading={cancel.isPending} onClick={() => cancel.mutate()}>{t("cancel.confirm")}</Button></>}>
      <div className="space-y-4">
        <Field label={t("cancel.reason")} required>
          <Select value={reason} onChange={(e) => setReason(e.target.value)} autoFocus>
            <option value="">{t("cancel.pickReason")}</option>
            {options.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
          </Select>
        </Field>
        <Field label={t("cancel.note")} required={needsNote}><Input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} /></Field>
        <p className="text-xs text-muted">{t("cancel.hint")}</p>
      </div>
    </Modal>
  );
}
