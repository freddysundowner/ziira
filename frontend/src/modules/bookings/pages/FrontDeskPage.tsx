import { Receipt, UserPlus } from "lucide-react";
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  api, Badge, Button, Card, cx, EmptyState, ErrorState, Input, PageHeader, Skeleton, toast, unwrap, useCan, useMutation, useQuery, useTranslation,
} from "@/sdk";

import { AppointmentDrawer } from "../components/AppointmentDrawer";
import { BookingForm } from "../components/BookingForm";
import { BranchPicker } from "../components/BranchBar";
import { PackSteps } from "../components/PackSteps";
import { nextStep, quickOffers, STATE_TONE, type StepName } from "../desk/logic";
import { useBranch, useOffers, useRefreshBookings } from "../hooks";
import { clock } from "../lib";
import type { FrontDeskBoard } from "../types";

type Person = FrontDeskBoard["resources"][number];
type Brief = FrontDeskBoard["arriving"][number];

const STEP_LABEL: Record<StepName, string> = { confirm: "confirm", "check-in": "checkIn", start: "start", finish: "finish" };

/** The live board of a branch: who is free, who is with a client, who waits, who arrives, who is ready to pay. */
export default function FrontDeskPage() {
  const { t } = useTranslation("bookings");
  const canManage = useCan("bookings.manage");
  const { branches, branchId, setBranchId, companyId, zone } = useBranch();
  const [open, setOpen] = useState<string | null>(null);
  const [detailed, setDetailed] = useState(false);
  const board = useQuery({
    queryKey: ["bookings", "board", branchId], enabled: !!branchId, refetchInterval: 20_000,
    queryFn: () => unwrap(api.GET("/api/v1/bookings/front-desk/board", { params: { query: { branch_id: branchId } } })),
  });
  const data = board.data;
  const empty = !!data && data.resources.length === 0 && data.waiting.length === 0 && data.arriving.length === 0 && data.in_service.length === 0 && data.to_bill.length === 0;

  return (
    <>
      <PageHeader title={t("frontDesk.title")} description={t("desk.hint")}
        actions={<>
          <BranchPicker branches={branches} value={branchId} onChange={setBranchId} />
          {canManage && <Button variant="secondary" onClick={() => setDetailed(true)}><UserPlus className="h-4 w-4" />{t("desk.walkInDetails")}</Button>}
        </>} />
      <div className="space-y-5">
        <PackSteps companyId={companyId} />
        {canManage && <WalkInStrip branchId={branchId} companyId={companyId} onStarted={setOpen} />}
        {board.isLoading && <BoardSkeleton />}
        {board.error && <ErrorState message={board.error.message} onRetry={() => void board.refetch()} />}
        {empty && <EmptyState title={t("desk.empty")} hint={t("desk.emptyHint")} />}
        {data && !empty && (
          <>
            {data.resources.length > 0 && (
              <section aria-label={t("desk.people")} className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {data.resources.map((p) => <PersonTile key={p.resource_id} person={p} zone={zone} onOpen={setOpen} />)}
              </section>
            )}
            <div className="grid gap-5 lg:grid-cols-2">
              <Queue id="to_bill" rows={data.to_bill} zone={zone} onOpen={setOpen} />
              <Queue id="in_service" rows={data.in_service} zone={zone} onOpen={setOpen} />
              <Queue id="waiting" rows={data.waiting} zone={zone} onOpen={setOpen} />
              <Queue id="arriving" rows={data.arriving} zone={zone} onOpen={setOpen} />
            </div>
          </>
        )}
      </div>
      <AppointmentDrawer appointmentId={open} onClose={() => setOpen(null)} zone={zone} />
      <BookingForm open={detailed} onClose={() => setDetailed(false)} branchId={branchId} companyId={companyId} zone={zone} walkIn onBooked={(id) => setOpen(id)} />
    </>
  );
}

function BoardSkeleton() {
  return <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-28 w-full" />)}</div>;
}

/** Two taps for a walk-in: the service, then Start now. A name or phone can be typed first, never has to be. */
function WalkInStrip({ branchId, companyId, onStarted }: { branchId: string; companyId: string; onStarted: (appointmentId: string) => void }) {
  const { t } = useTranslation("bookings");
  const refresh = useRefreshBookings();
  const offers = useOffers(companyId);
  const [picked, setPicked] = useState("");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const localId = useRef(crypto.randomUUID());
  const chips = quickOffers(offers.data ?? []);
  const start = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/bookings/front-desk/walk-in", {
      body: { offer_id: picked, branch_id: branchId, client_name: name.trim() || null, client_phone: phone.trim() || null, local_id: localId.current },
    })),
    onSuccess: (r) => {
      toast(r.wait_minutes === 0 ? t("desk.walkInNow") : t("desk.walkInQueue", { count: r.wait_minutes }), "ok");
      localId.current = crypto.randomUUID();
      setPicked(""); setName(""); setPhone("");
      void refresh();
      if (r.wait_minutes === 0) onStarted(r.appointment.id);
    },
  });
  if (offers.isLoading) return <Skeleton className="h-24 w-full" />;
  if (offers.error) return <ErrorState message={offers.error.message} onRetry={() => void offers.refetch()} />;
  if (chips.length === 0) return <EmptyState title={t("desk.noServices")} hint={t("desk.noServicesHint")} />;
  return (
    <Card title={t("desk.walkInTitle")} description={t("desk.walkInHint")}>
      <div role="group" aria-label={t("desk.walkInTitle")} className="flex flex-wrap gap-2">
        {chips.map((o) => (
          <button key={o.id} type="button" aria-pressed={picked === o.id} onClick={() => setPicked(picked === o.id ? "" : o.id)}
            className={cx("min-h-[48px] rounded-xl border px-4 text-sm font-semibold transition-colors",
              picked === o.id ? "border-brand bg-brand text-brand-ink" : "border-line bg-surface hover:bg-sunken")}>
            {o.name}
          </button>
        ))}
      </div>
      {picked && (
        <form className="mt-4 flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (!start.isPending) start.mutate(); }}>
          <Input className="w-full sm:w-52" aria-label={t("desk.clientName")} placeholder={t("desk.clientName")} value={name} maxLength={200} onChange={(e) => setName(e.target.value)} />
          <Input className="w-full sm:w-44" aria-label={t("desk.clientPhone")} placeholder={t("desk.clientPhone")} type="tel" value={phone} maxLength={30} onChange={(e) => setPhone(e.target.value)} />
          <Button type="submit" size="lg" loading={start.isPending} className="w-full sm:w-auto">{t("desk.startNow")}</Button>
        </form>
      )}
    </Card>
  );
}

function PersonTile({ person: p, zone, onOpen }: { person: Person; zone?: string; onOpen: (appointmentId: string) => void }) {
  const { t } = useTranslation("bookings");
  const target = p.current?.appointment_id ?? p.next?.appointment_id;
  const status =
    p.state === "free" ? (p.free_for_minutes ? t("desk.freeFor", { count: p.free_for_minutes }) : t("desk.freeNow"))
    : p.until ? t("desk.until", { time: clock(p.until, zone) }) : "";
  const body = (
    <>
      <span className="flex items-start justify-between gap-2">
        <span className="min-w-0">
          <span className="block truncate text-base font-bold">{p.name}</span>
          {p.level && <span className="block truncate text-xs text-muted">{p.level}</span>}
        </span>
        <Badge tone={STATE_TONE[p.state]}>{t(`desk.state.${p.state}`)}</Badge>
      </span>
      {status && <span className="mt-1 block text-sm font-medium tabular-nums">{status}</span>}
      {p.current && <span className="mt-1 block truncate text-sm">{[p.current.client_name, p.current.service].filter(Boolean).join(" · ")}</span>}
      {p.next && <span className="mt-1 block truncate text-xs text-muted">{t("desk.next", { time: clock(p.next.starts_at, zone), what: [p.next.client_name, p.next.service].filter(Boolean).join(" · ") })}</span>}
    </>
  );
  const cls = "block w-full rounded-xl border border-line bg-surface p-4 text-left shadow-card";
  return target
    ? <button type="button" onClick={() => onOpen(target)} className={cx(cls, "hover:border-muted/40")}>{body}</button>
    : <div className={cls}>{body}</div>;
}

const TITLE = { to_bill: "toBill", in_service: "inService", waiting: "waiting", arriving: "arriving" } as const;

/** One list of the board: waiting, arriving soon, with a client, or ready to bill. */
function Queue({ id, rows, zone, onOpen }: { id: keyof typeof TITLE; rows: Brief[]; zone?: string; onOpen: (appointmentId: string) => void }) {
  const { t } = useTranslation("bookings");
  const canManage = useCan("bookings.manage");
  const canCheckout = useCan("bookings.checkout");
  const navigate = useNavigate();
  const refresh = useRefreshBookings();
  const step = useMutation({
    mutationFn: (v: { id: string; step: StepName }) => unwrap(api.POST(`/api/v1/bookings/appointments/{appointment_id}/${v.step}` as "/api/v1/bookings/appointments/{appointment_id}/confirm", { params: { path: { appointment_id: v.id } } })),
    onSuccess: () => void refresh(),
  });
  const bill = useMutation({
    mutationFn: (appointmentId: string) => unwrap(api.POST("/api/v1/bookings/checkouts", { body: { appointment_ids: [appointmentId] } })),
    onSuccess: (co) => navigate(`/checkout/${co.id}`),
  });
  const busy = (appointmentId: string, s: string) => step.isPending && step.variables?.id === appointmentId && step.variables.step === s;
  const checkOut = (r: Brief, primary: boolean) => canCheckout && (
    <Button key="bill" size={primary ? "lg" : "md"} variant={primary ? "primary" : "secondary"} loading={bill.isPending && bill.variables === r.appointment_id} onClick={() => bill.mutate(r.appointment_id)}>
      <Receipt className="h-4 w-4" />{t("desk.checkOut")}
    </Button>
  );
  return (
    <Card title={`${t(`desk.queues.${TITLE[id]}`)} (${rows.length})`}>
      {rows.length === 0 ? <p className="py-2 text-sm text-muted">{t(`desk.queues.${TITLE[id]}Empty`)}</p> : (
        <ul className="divide-y divide-line">
          {rows.map((r) => {
            const next = nextStep(r.status);
            const waited = (r as { waited_minutes?: number }).waited_minutes ?? 0;
            return (
              <li key={r.appointment_id} className="flex flex-wrap items-center gap-3 py-3">
                <button type="button" onClick={() => onOpen(r.appointment_id)} className="flex min-w-0 flex-1 items-center gap-3 text-left">
                  <span className="w-14 shrink-0 text-lg font-semibold tabular-nums">{clock(r.starts_at, zone)}</span>
                  <span className="min-w-0">
                    <span className="block truncate font-medium">{r.client_name ?? "—"}</span>
                    <span className="block truncate text-xs text-muted">
                      {r.service}{id === "waiting" && waited > 0 && <> · {t("desk.waited", { count: waited })}</>}
                    </span>
                  </span>
                </button>
                <div className="flex flex-wrap gap-1.5">
                  {id === "to_bill" && checkOut(r, true)}
                  {id === "in_service" && canManage && next && (
                    <Button variant="secondary" loading={busy(r.appointment_id, next)} onClick={() => step.mutate({ id: r.appointment_id, step: next })}>{t(`actions.${STEP_LABEL[next]}`)}</Button>
                  )}
                  {id === "in_service" && checkOut(r, false)}
                  {(id === "waiting" || id === "arriving") && canManage && next && (
                    <Button loading={busy(r.appointment_id, next)} onClick={() => step.mutate({ id: r.appointment_id, step: next })}>{id === "arriving" ? t("desk.checkIn") : t(`actions.${STEP_LABEL[next]}`)}</Button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
