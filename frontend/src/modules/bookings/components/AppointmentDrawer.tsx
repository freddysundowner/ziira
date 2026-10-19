import { useState } from "react";

import {
  Alert, api, Button, ConfirmDialog, DetailList, Drawer, ErrorState, formatDate, Input, money, Skeleton, toast, unwrap, useCan, useCurrency, useMutation, useQuery, useTranslation,
} from "@/sdk";

import { useRefreshBookings, useResources } from "../hooks";
import { clock } from "../lib";
import type { Appointment } from "../types";
import { CancelDialog } from "./CancelDialog";
import { RescheduleDialog } from "./RescheduleDialog";
import { AppointmentExtras } from "./AppointmentExtras";
import { ClientCard } from "./ClientCard";
import { AppointmentStatus } from "./StatusBadge";

type Step = "confirm" | "check-in" | "start" | "finish" | "no-show";

/** One appointment: what it is, and what can be done with it next. */
export function AppointmentDrawer({ appointmentId, onClose, zone }: { appointmentId: string | null; onClose: () => void; zone?: string }) {
  const { t } = useTranslation("bookings");
  const canManage = useCan("bookings.manage");
  const canInvoice = useCan("bookings.checkout");
  const refresh = useRefreshBookings();
  const [cancelling, setCancelling] = useState(false);
  const [moving, setMoving] = useState(false);
  const [missing, setMissing] = useState(false);
  const [card, setCard] = useState(false);
  const query = useQuery({
    queryKey: ["bookings", "appointment", appointmentId], enabled: !!appointmentId,
    queryFn: () => unwrap(api.GET("/api/v1/bookings/appointments/{appointment_id}", { params: { path: { appointment_id: appointmentId as string } } })),
  });
  const a = query.data;
  const currency = useCurrency(a?.company_id);
  const settings = useQuery({
    queryKey: ["bookings", "settings", a?.company_id], enabled: !!a,
    queryFn: () => unwrap(api.GET("/api/v1/bookings/settings", { params: { query: { company_id: a?.company_id as string } } })),
  });
  const settingsInvoicing = settings.data?.invoicing_available ?? true;
  const resources = useResources(a?.branch_id ?? "", false);
  const names = (a?.resource_ids ?? []).map((id) => resources.data?.find((r) => r.id === id)?.name).filter(Boolean).join(", ");

  const step = useMutation({
    mutationFn: (s: Step) => unwrap(api.POST(`/api/v1/bookings/appointments/{appointment_id}/${s}` as "/api/v1/bookings/appointments/{appointment_id}/confirm", { params: { path: { appointment_id: appointmentId as string } } })),
    onSuccess: () => { void refresh(); },
  });
  const invoice = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/bookings/appointments/{appointment_id}/invoice", { params: { path: { appointment_id: appointmentId as string } } })),
    onSuccess: (done) => { void refresh(); toast(t("drawer.invoiced", { number: done.invoice_number }), "ok"); },
  });

  const actions = (x: Appointment) => {
    if (!canManage) return null;
    const go = (s: Step, label: string, primary = false) => (
      <Button key={s} variant={primary ? "primary" : "secondary"} loading={step.isPending && step.variables === s} onClick={() => step.mutate(s)}>{label}</Button>
    );
    const out = [];
    if (x.status === "requested") out.push(go("confirm", t("actions.confirm"), true));
    if (x.status === "confirmed") out.push(go("check-in", t("actions.checkIn"), true));
    if (x.status === "checked_in") out.push(go("start", t("actions.start"), true));
    if (x.status === "in_service") out.push(go("finish", t("actions.finish"), true));
    if (x.status === "completed" && !x.invoice_id && x.kind === "appointment" && settingsInvoicing && canInvoice) {
      out.push(<Button key="invoice" loading={invoice.isPending} onClick={() => invoice.mutate()}>{t("actions.createInvoice")}</Button>);
    }
    if (x.status === "requested" || x.status === "confirmed") out.push(<Button key="move" variant="secondary" onClick={() => setMoving(true)}>{t("actions.reschedule")}</Button>);
    if (["requested", "confirmed", "checked_in"].includes(x.status)) out.push(<Button key="cancel" variant="secondary" onClick={() => setCancelling(true)}>{t("actions.cancel")}</Button>);
    if (["confirmed", "checked_in"].includes(x.status) && new Date(x.starts_at) <= new Date()) out.push(<Button key="noshow" variant="ghost" onClick={() => setMissing(true)}>{t("actions.noShow")}</Button>);
    return out;
  };

  return (
    <>
      <Drawer open={!!appointmentId} onClose={onClose} title={a ? t("drawer.title", { number: a.number }) : t("drawer.loading")}>
        {query.isLoading && <div className="space-y-3"><Skeleton className="h-6 w-40" /><Skeleton className="h-32 w-full" /></div>}
        {query.error && <ErrorState message={query.error.message} onRetry={() => void query.refetch()} />}
        {a && (
          <div className="space-y-5">
            <div className="flex items-center gap-2"><AppointmentStatus status={a.status} />{a.late_cancellation && <span className="text-xs font-medium text-bad">{t("drawer.late")}</span>}</div>
            {a.status === "requested" && <Alert tone="warn">{t("drawer.requestedHint")}</Alert>}
            {a.status === "completed" && !a.invoice_id && !settingsInvoicing && <Alert tone="info">{t("drawer.noInvoicing")}</Alert>}
            <DetailList items={[
              { label: t("drawer.service"), value: a.service },
              { label: t("drawer.when"), value: `${formatDate(a.starts_at)} ${clock(a.starts_at, zone)} - ${clock(a.ends_at, zone)}` },
              { label: t("drawer.with"), value: names || "—" },
              { label: t("drawer.client"), value: a.client_name ?? "—" },
              { label: t("drawer.phone"), value: a.client_phone ?? "—" },
              { label: t("drawer.email"), value: a.client_email ?? "—" },
              { label: t("drawer.price"), value: money(a.price, currency) },
              { label: t("drawer.source"), value: t(`source.${a.source}`, a.source) },
              ...(a.minutes_worked != null ? [{ label: t("drawer.minutes"), value: String(a.minutes_worked) }] : []),
              ...(a.invoice_number ? [{ label: t("drawer.invoice"), value: a.invoice_number }] : []),
              ...(a.note ? [{ label: t("drawer.note"), value: a.note }] : []),
            ]} />
            {a.kind === "appointment" && <AppointmentExtras a={a} onClient={() => setCard(true)} />}
            {a.kind === "class" && <Attendees appointment={a} />}
            <div className="flex flex-wrap gap-2">{actions(a)}</div>
          </div>
        )}
      </Drawer>
      {a?.customer_id && <ClientCard customerId={card ? a.customer_id : null} companyId={a.company_id} name={a.client_name} onClose={() => setCard(false)} />}
      {a && <CancelDialog appointment={a} open={cancelling} onClose={() => setCancelling(false)} />}
      {a && <RescheduleDialog appointment={a} open={moving} onClose={() => setMoving(false)} zone={zone} />}
      <ConfirmDialog open={missing} onClose={() => setMissing(false)} title={t("noShow.title")} message={t("noShow.message")} confirmLabel={t("actions.noShow")} danger busy={step.isPending}
        onConfirm={() => step.mutate("no-show", { onSuccess: () => setMissing(false) })} />
    </>
  );
}

/** A class: who is on it, with room for more until it is full. */
function Attendees({ appointment }: { appointment: Appointment }) {
  const { t } = useTranslation("bookings");
  const canManage = useCan("bookings.manage");
  const refresh = useRefreshBookings();
  const [name, setName] = useState("");
  const list = useQuery({
    queryKey: ["bookings", "attendees", appointment.id],
    queryFn: () => unwrap(api.GET("/api/v1/bookings/appointments/{appointment_id}/attendees", { params: { path: { appointment_id: appointment.id } } })),
  });
  const add = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/bookings/appointments/{appointment_id}/attendees", { params: { path: { appointment_id: appointment.id } }, body: { name: name.trim() } })),
    onSuccess: () => { setName(""); void refresh(); },
  });
  const mark = useMutation({
    mutationFn: (v: { id: string; status: "booked" | "attended" | "no_show" | "cancelled" }) => unwrap(api.PATCH("/api/v1/bookings/attendees/{attendee_id}", { params: { path: { attendee_id: v.id } }, body: { status: v.status } })),
    onSuccess: () => void refresh(),
  });
  const people = list.data ?? [];
  return (
    <section aria-label={t("drawer.attendees")}>
      <h3 className="mb-2 text-sm font-semibold">{t("drawer.attendeesCount", { count: appointment.attendees, capacity: appointment.capacity })}</h3>
      {list.error && <ErrorState message={list.error.message} onRetry={() => void list.refetch()} />}
      {people.length === 0 && !list.isLoading && <p className="text-sm text-muted">{t("drawer.noAttendees")}</p>}
      <ul className="divide-y divide-line">
        {people.map((p) => (
          <li key={p.id} className="flex items-center justify-between gap-2 py-2 text-sm">
            <span className={p.status === "cancelled" ? "text-muted line-through" : ""}>{p.name}</span>
            {canManage && p.status !== "cancelled" && (
              <span className="flex gap-1">
                <Button size="sm" variant={p.status === "attended" ? "primary" : "secondary"} onClick={() => mark.mutate({ id: p.id, status: "attended" })}>{t("drawer.attended")}</Button>
                <Button size="sm" variant="ghost" onClick={() => mark.mutate({ id: p.id, status: "cancelled" })}>{t("drawer.remove")}</Button>
              </span>
            )}
          </li>
        ))}
      </ul>
      {canManage && appointment.attendees < appointment.capacity && (
        <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (name.trim()) add.mutate(); }}>
          <Input aria-label={t("drawer.attendeeName")} placeholder={t("drawer.attendeeName")} value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
          <Button type="submit" loading={add.isPending} disabled={!name.trim()}>{t("drawer.add")}</Button>
        </form>
      )}
    </section>
  );
}
