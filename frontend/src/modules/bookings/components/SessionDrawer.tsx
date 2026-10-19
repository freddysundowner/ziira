import { useEffect, useState } from "react";

import { api, Alert, Badge, Button, ConfirmDialog, Drawer, EmptyState, ErrorState, Field, formatDate, FormGrid, Input, Select, SkeletonRows, toast, unwrap, useCan, useMutation, useQuery, useTranslation } from "@/sdk";

import { ClientPicker } from "../ops/ClientPicker";
import { useReasons, useRefreshBookings, useResources } from "../hooks";
import { clock, dayOf } from "../lib";
import type { ClassSession } from "../types";


/** One group session: who is booked, who waits, and what the front desk can change. */
export function SessionDrawer({ sessionId, companyId, zone, onClose }: { sessionId: string | null; companyId: string; zone?: string; onClose: () => void }) {
  const { t } = useTranslation("bookings");
  const canManage = useCan("bookings.manage");
  const open = sessionId !== null;
  const detail = useQuery<ClassSession>({
    queryKey: ["bookings", "session", sessionId], enabled: open,
    queryFn: () => unwrap(api.GET("/api/v1/bookings/sessions/{session_id}", { params: { path: { session_id: sessionId as string } } })),
  });
  const s = detail.data;
  const resources = useResources(s?.branch_id ?? "", false);
  const names = (s?.resource_ids ?? []).map((id) => resources.data?.find((r) => r.id === id)?.name).filter(Boolean).join(", ");
  const cancelled = s?.status === "cancelled";

  return (
    <Drawer open={open} onClose={onClose} title={s ? s.name : t("classes.session")}>
      {detail.isLoading && <SkeletonRows rows={4} cols={2} />}
      {detail.error && <ErrorState message={detail.error.message} onRetry={() => void detail.refetch()} />}
      {s && (
        <div className="space-y-6">
          <div className="space-y-1 text-sm">
            <p className="font-semibold">{formatDate(dayOf(s.starts_at, zone))} · {clock(s.starts_at, zone)}–{clock(s.ends_at, zone)}</p>
            <p className="text-muted">{names || t("classes.noInstructor")}</p>
            <div className="flex flex-wrap gap-1.5 pt-1">
              <Badge tone={s.free === 0 ? "warn" : "ok"}>{t("classes.places", { booked: s.booked, capacity: s.capacity })}</Badge>
              {s.waiting > 0 && <Badge tone="info">{t("classes.waiting", { count: s.waiting })}</Badge>}
              {cancelled && <Badge tone="bad">{t("classes.cancelledBadge")}</Badge>}
            </div>
          </div>
          <Roster session={s} companyId={companyId} canManage={canManage && !cancelled} />
          <WaitingList session={s} zone={zone} canManage={canManage && !cancelled} />
          {canManage && !cancelled && <Changes session={s} onCancelled={onClose} />}
        </div>
      )}
    </Drawer>
  );
}

function Roster({ session, companyId, canManage }: { session: ClassSession; companyId: string; canManage: boolean }) {
  const { t } = useTranslation("bookings");
  const refresh = useRefreshBookings();
  const roster = useQuery({
    queryKey: ["bookings", "session", session.id, "roster"],
    queryFn: () => unwrap(api.GET("/api/v1/bookings/sessions/{session_id}/roster", { params: { path: { session_id: session.id } } })),
  });
  const mark = useMutation({
    mutationFn: (v: { id: string; status: "attended" | "no_show" }) => unwrap(api.PATCH("/api/v1/bookings/attendees/{attendee_id}", { params: { path: { attendee_id: v.id } }, body: { status: v.status } })),
    onSuccess: () => { void refresh(); toast(t("classes.marked"), "ok"); },
  });
  const cancel = useMutation({
    mutationFn: (id: string) => unwrap(api.POST("/api/v1/bookings/sessions/attendees/{attendee_id}/cancel", { params: { path: { attendee_id: id } } })),
    onSuccess: (a) => { void refresh(); toast(a.late_cancellation ? t("classes.cancelledLate") : t("classes.personCancelled"), "ok"); },
  });
  const busyId = (mark.isPending && mark.variables?.id) || (cancel.isPending && cancel.variables) || "";

  return (
    <section aria-label={t("classes.roster")} className="space-y-3">
      <h3 className="text-sm font-bold">{t("classes.roster")}</h3>
      {roster.isLoading && <SkeletonRows rows={3} cols={2} />}
      {roster.error && <ErrorState message={roster.error.message} onRetry={() => void roster.refetch()} />}
      {roster.data && roster.data.length === 0 && <EmptyState title={t("classes.rosterEmpty")} hint={canManage ? t("classes.rosterEmptyHint") : undefined} />}
      <ul className="space-y-2">
        {(roster.data ?? []).map((a) => (
          <li key={a.id} className="rounded-xl border border-line p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="truncate font-medium">{a.name}</p>
                {a.phone && <p className="text-xs text-muted">{a.phone}</p>}
              </div>
              <div className="flex flex-wrap gap-1.5">
                <Badge tone={a.status === "attended" ? "ok" : a.status === "no_show" ? "bad" : a.status === "cancelled" ? "neutral" : "info"}>{t(`classes.attendee.${a.status}`, a.status)}</Badge>
                {a.late_cancellation && <Badge tone="warn">{t("classes.lateBadge")}</Badge>}
              </div>
            </div>
            {canManage && a.status === "booked" && (
              <div className="mt-2 flex flex-wrap gap-2">
                <Button size="sm" loading={busyId === a.id} onClick={() => mark.mutate({ id: a.id, status: "attended" })}>{t("classes.attended")}</Button>
                <Button size="sm" variant="secondary" disabled={busyId === a.id} onClick={() => mark.mutate({ id: a.id, status: "no_show" })}>{t("classes.noShow")}</Button>
                <Button size="sm" variant="ghost" disabled={busyId === a.id} onClick={() => cancel.mutate(a.id)}>{t("classes.cancelPerson")}</Button>
              </div>
            )}
          </li>
        ))}
      </ul>
      {canManage && <AddPerson session={session} companyId={companyId} />}
    </section>
  );
}

function AddPerson({ session, companyId }: { session: ClassSession; companyId: string }) {
  const { t } = useTranslation("bookings");
  const refresh = useRefreshBookings();
  const [client, setClient] = useState("");
  const [label, setLabel] = useState<string | undefined>();
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const book = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/bookings/sessions/{session_id}/book", { params: { path: { session_id: session.id } }, body: client ? { customer_id: client, join_waitlist: true } : { name: name.trim(), phone: phone.trim() || null, join_waitlist: true } })),
    onSuccess: (r) => {
      void refresh();
      toast(r.status === "booked" ? t("classes.booked") : t("classes.waitlisted", { position: r.position ?? 1 }), r.status === "booked" ? "ok" : "info");
      setClient(""); setLabel(undefined); setName(""); setPhone("");
    },
  });
  const ready = !!client || name.trim().length > 0;
  return (
    <form className="space-y-3 rounded-xl bg-sunken p-3" onSubmit={(e) => { e.preventDefault(); if (ready) book.mutate(); }}>
      <p className="text-sm font-semibold">{session.free > 0 ? t("classes.addPerson") : t("classes.addPersonFull")}</p>
      <Field label={t("classes.findClient")}>
        <ClientPicker companyId={companyId} value={client} label={label} placeholder={t("classes.findClient")} onChange={(id, n) => { setClient(id); setLabel(n); }} />
      </Field>
      {!client && (
        <FormGrid>
          <Field label={t("classes.orName")}><Input value={name} maxLength={200} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label={t("classes.phone")}><Input type="tel" value={phone} maxLength={30} onChange={(e) => setPhone(e.target.value)} /></Field>
        </FormGrid>
      )}
      <Button type="submit" disabled={!ready} loading={book.isPending}>{session.free > 0 ? t("classes.book") : t("classes.joinWaitlist")}</Button>
    </form>
  );
}

function WaitingList({ session, zone, canManage }: { session: ClassSession; zone?: string; canManage: boolean }) {
  const { t } = useTranslation("bookings");
  const refresh = useRefreshBookings();
  const list = useQuery({
    queryKey: ["bookings", "session", session.id, "waitlist"],
    queryFn: () => unwrap(api.GET("/api/v1/bookings/sessions/{session_id}/waitlist", { params: { path: { session_id: session.id } } })),
  });
  const confirm = useMutation({
    mutationFn: (id: string) => unwrap(api.POST("/api/v1/bookings/sessions/waitlist/{waitlist_id}/confirm", { params: { path: { waitlist_id: id } } })),
    onSuccess: () => { void refresh(); toast(t("classes.booked"), "ok"); },
  });
  const [removing, setRemoving] = useState<string | null>(null);
  const leave = useMutation({
    mutationFn: (id: string) => unwrap(api.POST("/api/v1/bookings/sessions/waitlist/{waitlist_id}/leave", { params: { path: { waitlist_id: id } } })),
    onSuccess: () => { void refresh(); setRemoving(null); toast(t("classes.removed"), "ok"); },
  });
  const rows = (list.data ?? []).filter((w) => w.status === "waiting" || w.status === "offered");
  if (list.isLoading || (!list.error && rows.length === 0)) return null;
  return (
    <section aria-label={t("classes.waitlist")} className="space-y-3">
      <h3 className="text-sm font-bold">{t("classes.waitlist")}</h3>
      {list.error && <ErrorState message={list.error.message} onRetry={() => void list.refetch()} />}
      <ul className="space-y-2">
        {rows.map((w, i) => (
          <li key={w.id} className="rounded-xl border border-line p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="truncate font-medium">{i + 1}. {w.name}</p>
                {w.phone && <p className="text-xs text-muted">{w.phone}</p>}
              </div>
              {w.status === "offered" && w.confirm_by && <Badge tone="info">{t("classes.offeredUntil", { time: clock(w.confirm_by, zone) })}</Badge>}
            </div>
            {canManage && (
              <div className="mt-2 flex flex-wrap gap-2">
                {w.status === "offered" && <Button size="sm" loading={confirm.isPending && confirm.variables === w.id} onClick={() => confirm.mutate(w.id)}>{t("classes.saidYes")}</Button>}
                <Button size="sm" variant="ghost" onClick={() => setRemoving(w.id)}>{t("classes.removeWaiting")}</Button>
              </div>
            )}
          </li>
        ))}
      </ul>
      <ConfirmDialog open={!!removing} onClose={() => setRemoving(null)} title={t("classes.removeWaitingTitle")} message={t("classes.removeWaitingMessage")} danger busy={leave.isPending}
        confirmLabel={t("classes.removeWaiting")} onConfirm={() => removing && leave.mutate(removing)} />
    </section>
  );
}

function Changes({ session, onCancelled }: { session: ClassSession; onCancelled: () => void }) {
  const { t } = useTranslation("bookings");
  const refresh = useRefreshBookings();
  const resources = useResources(session.branch_id);
  const reasons = useReasons("appointment_cancel");
  const people = (resources.data ?? []).filter((r) => r.kind === "staff");
  const current = session.resource_ids.find((id) => people.some((p) => p.id === id)) ?? "";
  const [capacity, setCapacity] = useState(String(session.capacity));
  const [instructor, setInstructor] = useState(current);
  const [confirming, setConfirming] = useState(false);
  const [reason, setReason] = useState("");
  const [missing, setMissing] = useState(false);
  useEffect(() => { setCapacity(String(session.capacity)); }, [session.capacity]);
  useEffect(() => { setInstructor(current); }, [current]);

  const saveCapacity = useMutation({
    mutationFn: () => unwrap(api.PUT("/api/v1/bookings/sessions/{session_id}/capacity", { params: { path: { session_id: session.id } }, body: { capacity: Math.max(1, Math.floor(Number(capacity)) || 1) } })),
    onSuccess: () => { void refresh(); toast(t("classes.saved"), "ok"); },
  });
  const saveInstructor = useMutation({
    mutationFn: () => unwrap(api.PUT("/api/v1/bookings/sessions/{session_id}/instructor", { params: { path: { session_id: session.id } }, body: { resource_id: instructor } })),
    onSuccess: () => { void refresh(); toast(t("classes.saved"), "ok"); },
  });
  const cancel = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/bookings/sessions/{session_id}/cancel", { params: { path: { session_id: session.id } }, body: { reason_code_id: reason } })),
    onSuccess: () => { void refresh(); setConfirming(false); toast(t("classes.classCancelled"), "ok"); onCancelled(); },
  });

  return (
    <section aria-label={t("classes.changes")} className="space-y-4">
      <h3 className="text-sm font-bold">{t("classes.changes")}</h3>
      <div className="flex items-end gap-2">
        <Field label={t("classes.capacity")} className="flex-1"><Input type="number" inputMode="numeric" min={1} max={500} value={capacity} onChange={(e) => setCapacity(e.target.value)} /></Field>
        <Button variant="secondary" loading={saveCapacity.isPending} disabled={Number(capacity) === session.capacity || !capacity} onClick={() => saveCapacity.mutate()}>{t("save")}</Button>
      </div>
      <div className="flex items-end gap-2">
        <Field label={t("classes.instructor")} className="flex-1">
          <Select value={instructor} onChange={(e) => setInstructor(e.target.value)}>
            <option value="">{t("classes.pickInstructor")}</option>
            {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </Select>
        </Field>
        <Button variant="secondary" loading={saveInstructor.isPending} disabled={!instructor || instructor === current} onClick={() => saveInstructor.mutate()}>{t("save")}</Button>
      </div>
      <Button variant="danger" onClick={() => { setReason(""); setMissing(false); setConfirming(true); }}>{t("classes.cancelClass")}</Button>
      <ConfirmDialog open={confirming} onClose={() => setConfirming(false)} danger busy={cancel.isPending} title={t("classes.cancelClassTitle", { name: session.name })} confirmLabel={t("classes.cancelClass")}
        onConfirm={() => { if (!reason) { setMissing(true); return; } cancel.mutate(); }}
        message={
          <div className="space-y-3">
            <Alert tone="warn">{t("classes.cancelClassWarning", { count: session.booked + session.waiting })}</Alert>
            <Field label={t("cancel.reason")} required error={missing && !reason ? t("classes.reasonNeeded") : null}>
              <Select value={reason} onChange={(e) => { setReason(e.target.value); setMissing(false); }}>
                <option value="">{t("cancel.pickReason")}</option>
                {(reasons.data ?? []).filter((r) => r.code !== "NO_SHOW").map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
              </Select>
            </Field>
          </div>
        } />
    </section>
  );
}
