import { useState } from "react";

import { api, Button, ConfirmDialog, toast, unwrap, useCan, useMutation, useTranslation } from "@/sdk";

import { useRefreshBookings } from "../hooks";
import type { Appointment } from "../types";
import { CancelDialog } from "./CancelDialog";

type Step = "confirm" | "check-in" | "start" | "finish" | "no-show";
const NEXT: Record<string, { step: Step; label: string } | undefined> = {
  requested: { step: "confirm", label: "confirm" }, confirmed: { step: "check-in", label: "checkIn" },
  checked_in: { step: "start", label: "start" }, in_service: { step: "finish", label: "finish" },
};

/** The next step for an appointment as one button, plus the other things a front desk does with it (no-show, cancel, invoice). */
export function QuickActions({ appointment: a, invoicing = true, compact }: { appointment: Appointment; invoicing?: boolean; compact?: boolean }) {
  const { t } = useTranslation("bookings");
  const canManage = useCan("bookings.manage");
  const canInvoice = useCan("invoices.manage");
  const refresh = useRefreshBookings();
  const [missing, setMissing] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const size = compact ? "sm" : "md";
  const step = useMutation({
    mutationFn: (s: Step) => unwrap(api.POST(`/api/v1/bookings/appointments/{appointment_id}/${s}` as "/api/v1/bookings/appointments/{appointment_id}/confirm", { params: { path: { appointment_id: a.id } } })),
    onSuccess: () => { void refresh(); setMissing(false); },
  });
  const invoice = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/bookings/appointments/{appointment_id}/invoice", { params: { path: { appointment_id: a.id } } })),
    onSuccess: (done) => { void refresh(); toast(t("drawer.invoiced", { number: done.invoice_number }), "ok"); },
  });
  if (!canManage) return null;
  const next = NEXT[a.status];
  const started = new Date(a.starts_at) <= new Date();
  return (
    <div className="flex flex-wrap gap-1.5" onClick={(e) => e.stopPropagation()}>
      {next && <Button size={size} loading={step.isPending && step.variables === next.step} onClick={() => step.mutate(next.step)}>{t(`actions.${next.label}`)}</Button>}
      {a.status === "completed" && !a.invoice_id && a.kind === "appointment" && invoicing && canInvoice && (
        <Button size={size} loading={invoice.isPending} onClick={() => invoice.mutate()}>{t("actions.createInvoice")}</Button>
      )}
      {["confirmed", "checked_in"].includes(a.status) && started && <Button size={size} variant="ghost" onClick={() => setMissing(true)}>{t("actions.noShow")}</Button>}
      {["requested", "confirmed", "checked_in"].includes(a.status) && <Button size={size} variant="ghost" onClick={() => setCancelling(true)}>{t("actions.cancel")}</Button>}
      <ConfirmDialog open={missing} onClose={() => setMissing(false)} title={t("noShow.title")} message={t("noShow.message")} confirmLabel={t("actions.noShow")} danger busy={step.isPending}
        onConfirm={() => step.mutate("no-show")} />
      <CancelDialog appointment={a} open={cancelling} onClose={() => setCancelling(false)} />
    </div>
  );
}
