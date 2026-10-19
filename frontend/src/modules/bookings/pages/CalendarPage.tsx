import { ChevronLeft, ChevronRight, Plus } from "lucide-react";
import { useState } from "react";

import { Button, formatDate, IconButton, Input, PageHeader, Select, Tabs, today, useCan, useTranslation } from "@/sdk";

import { AppointmentDrawer } from "../components/AppointmentDrawer";
import { BookingForm, type BookingPreset } from "../components/BookingForm";
import { BranchPicker } from "../components/BranchBar";
import { Calendar } from "../components/Calendar";
import { RescheduleDialog } from "../components/RescheduleDialog";
import { WaitlistForm } from "../components/WaitlistForm";
import { useBranch, useResources } from "../hooks";
import { addDays, weekStart } from "../lib";
import type { Appointment } from "../types";

export default function CalendarPage() {
  const { t } = useTranslation("bookings");
  const canManage = useCan("bookings.manage");
  const { branches, branchId, setBranchId, companyId, zone, isLoading } = useBranch();
  const resources = useResources(branchId);
  const [view, setView] = useState<"day" | "week">("day");
  const [day, setDay] = useState(today());
  const [resourceId, setResourceId] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [booking, setBooking] = useState<{ preset?: BookingPreset; walkIn?: boolean } | null>(null);
  const [moving, setMoving] = useState<{ a: Appointment; startIso: string; resourceId: string } | null>(null);
  const [waitlist, setWaitlist] = useState<{ offerId: string; day: string } | null>(null);
  const step = view === "week" ? 7 : 1;
  const label = view === "week" ? `${formatDate(weekStart(day))} – ${formatDate(addDays(weekStart(day), 6))}` : formatDate(day);

  return (
    <>
      <PageHeader title={t("calendar.title")} description={t("calendar.hint")}
        actions={canManage && (
          <>
            <Button variant="secondary" onClick={() => setBooking({ walkIn: true })}>{t("frontDesk.walkIn")}</Button>
            <Button onClick={() => setBooking({})}><Plus className="h-4 w-4" />{t("calendar.newAppointment")}</Button>
          </>
        )} />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <BranchPicker branches={branches} value={branchId} onChange={setBranchId} />
        <Tabs tabs={[{ id: "day", label: t("calendar.day") }, { id: "week", label: t("calendar.week") }]} value={view} onChange={setView} />
        <div className="flex items-center gap-1">
          <IconButton label={t("calendar.previous")} onClick={() => setDay(addDays(day, -step))}><ChevronLeft className="h-4 w-4" /></IconButton>
          <Button variant="secondary" size="sm" onClick={() => setDay(today())}>{t("calendar.today")}</Button>
          <IconButton label={t("calendar.next")} onClick={() => setDay(addDays(day, step))}><ChevronRight className="h-4 w-4" /></IconButton>
        </div>
        <Input className="w-40" type="date" aria-label={t("form.date")} value={day} onChange={(e) => e.target.value && setDay(e.target.value)} />
        <span className="text-sm font-medium" aria-live="polite">{label}</span>
        {(resources.data?.length ?? 0) > 1 && (
          <Select className="w-44" aria-label={t("calendar.person")} value={resourceId} onChange={(e) => setResourceId(e.target.value)}>
            {view === "day" && <option value="">{t("calendar.everyone")}</option>}
            {(resources.data ?? []).map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </Select>
        )}
      </div>
      {!isLoading && !branchId ? null : (
        <Calendar branchId={branchId} day={day} view={view} resourceId={resourceId || undefined} zone={zone}
          onOpen={(a) => setOpen(a.id)}
          onPick={canManage ? (slot) => setBooking({ preset: slot }) : undefined}
          onMove={canManage ? (a, to) => setMoving({ a, ...to }) : undefined} />
      )}
      <AppointmentDrawer appointmentId={open} onClose={() => setOpen(null)} zone={zone} />
      <BookingForm open={!!booking} onClose={() => setBooking(null)} branchId={branchId} companyId={companyId} zone={zone} preset={booking?.preset} walkIn={booking?.walkIn}
        onWaitlist={(offerId, d) => { setBooking(null); setWaitlist({ offerId, day: d }); }} onBooked={(id) => setOpen(id)} />
      {moving && <RescheduleDialog appointment={moving.a} open onClose={() => setMoving(null)} zone={zone} preset={{ startIso: moving.startIso, resourceId: moving.resourceId }} />}
      <WaitlistForm open={!!waitlist} onClose={() => setWaitlist(null)} branchId={branchId} companyId={companyId} offerId={waitlist?.offerId} day={waitlist?.day} />
    </>
  );
}
