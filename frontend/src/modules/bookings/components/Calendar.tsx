import { type DragEvent, type KeyboardEvent, type MouseEvent, useMemo, useRef } from "react";

import { api, cx, ErrorState, formatDate, SkeletonRows, unwrap, useQuery, useTranslation } from "@/sdk";

import { useNow } from "../hooks";
import {
  addDays, BLOCK_CLASS, clock, dayOf, gridRange, hhmm, isStatus, minuteAt, minutesOfDay, offStretches, place, STATUSES, type Status, weekStart,
  workingStretches, zonedIso,
} from "../lib";
import type { Appointment, Resource, TimeOff } from "../types";

export interface CalendarProps {
  branchId: string;
  /** The day shown (day view) or any day of the week shown (week view), YYYY-MM-DD on the company's clock. */
  day: string;
  view: "day" | "week";
  /** Week view: whose week. Day view: leave empty for everyone, or show only this one. */
  resourceId?: string;
  zone?: string;
  /** Someone clicked an empty time: book it. */
  onPick?: (slot: { resourceId: string; startIso: string }) => void;
  /** Someone opened an appointment. */
  onOpen?: (appointment: Appointment) => void;
  /** Someone dropped an appointment on another time or resource (only requested and confirmed ones can be moved). */
  onMove?: (appointment: Appointment, to: { resourceId: string; startIso: string }) => void;
}

const HOUR_PX = 56;
const MOVABLE: readonly string[] = ["requested", "confirmed"];

interface Column {
  key: string;
  title: string;
  subtitle?: string;
  day: string;
  resource: Resource;
}

/** The shared diary: day view (a column per person or room) or week view (a column per day for one person). On a phone it becomes an agenda list. */
export function Calendar({ branchId, day, view, resourceId, zone, onPick, onOpen, onMove }: CalendarProps) {
  const { t } = useTranslation("bookings");
  const days = useMemo(() => (view === "week" ? Array.from({ length: 7 }, (_, i) => addDays(weekStart(day), i)) : [day]), [view, day]);
  const first = days[0] as string;
  const last = days.at(-1) as string;
  const query = useQuery({
    queryKey: ["bookings", "calendar", branchId, first, last, zone],
    enabled: !!branchId,
    refetchInterval: 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/bookings/calendar", { params: { query: { branch_id: branchId, start: zonedIso(first, "00:00", zone), end: zonedIso(addDays(last, 1), "00:00", zone) } } })),
  });
  const now = useNow();
  const drag = useRef<{ id: string; grab: number } | null>(null);

  const data = query.data;
  const shownResources = useMemo(() => {
    const all = data?.resources ?? [];
    if (view === "week") return all.filter((r) => r.id === (resourceId || all[0]?.id));
    return resourceId ? all.filter((r) => r.id === resourceId) : all;
  }, [data, view, resourceId]);

  const columns: Column[] = useMemo(() => (
    view === "week"
      ? shownResources.flatMap((r) => days.map((d) => ({ key: `${r.id}:${d}`, title: formatDate(d), subtitle: undefined, day: d, resource: r })))
      : shownResources.map((r) => ({ key: r.id, title: r.name, subtitle: t(`kinds.${r.kind}`, r.kind), day, resource: r }))
  ), [view, shownResources, days, day, t]);

  const appointments = useMemo(() => data?.appointments ?? [], [data]);
  const range = useMemo(() => gridRange(
    shownResources.map((r) => r.hours), days,
    appointments.map((a) => ({ start: minutesOfDay(a.starts_at, zone), end: minutesOfDay(a.ends_at, zone) || 24 * 60 }))), [shownResources, days, appointments, zone]);
  const hours = Array.from({ length: (range.end - range.start) / 60 }, (_, i) => range.start + i * 60);

  if (query.isLoading) return <SkeletonRows rows={6} cols={4} />;
  if (query.error || !data) return <ErrorState message={query.error?.message} onRetry={() => void query.refetch()} />;
  if (shownResources.length === 0) return <ErrorState title={t("calendar.noResources")} message={t("calendar.noResourcesHint")} />;

  const inColumn = (c: Column) => appointments.filter((a) => a.resource_ids.includes(c.resource.id) && dayOf(a.starts_at, zone) === c.day);
  const off = (c: Column) => offStretches(data.time_off.filter((o: TimeOff) => o.resource_id === c.resource.id), c.day, zone);
  const today = dayOf(now, zone);
  const nowMin = minutesOfDay(now, zone);

  const slotFromEvent = (e: MouseEvent | DragEvent, c: Column, grab = 0) => {
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const minute = minuteAt((e.clientY - rect.top) / rect.height, range) - grab;
    return { resourceId: c.resource.id, startIso: zonedIso(c.day, hhmm(Math.max(minute, 0)), zone) };
  };

  const onKey = (e: KeyboardEvent, a: Appointment) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen?.(a); }
  };

  return (
    <div>
      <div className="hidden overflow-x-auto rounded-xl border border-line bg-surface shadow-card md:block" role="group" aria-label={t("calendar.gridLabel")}>
        <div className="flex min-w-max">
          <div className="sticky left-0 z-20 w-14 shrink-0 border-r border-line bg-surface">
            <div className="h-12 border-b border-line" />
            <div className="relative" style={{ height: hours.length * HOUR_PX }}>
              {hours.map((h, i) => <span key={h} className="absolute right-2 -translate-y-1/2 text-xs text-muted" style={{ top: i * HOUR_PX, display: i === 0 ? "none" : undefined }}>{hhmm(h)}</span>)}
            </div>
          </div>
          {columns.map((c) => (
            <div key={c.key} className={cx("min-w-[9rem] flex-1 border-r border-line last:border-r-0", c.day === today && view === "week" && "bg-brand-soft/20")}>
              <div className="flex h-12 flex-col items-center justify-center border-b border-line px-2 text-center">
                <span className="truncate text-sm font-medium">{c.title}</span>
                {c.subtitle && <span className="text-xs text-muted">{c.subtitle}</span>}
              </div>
              <div
                className="relative cursor-cell bg-sunken" style={{ height: hours.length * HOUR_PX }}
                onClick={(e) => { if (e.target === e.currentTarget || (e.target as HTMLElement).dataset.slot) onPick?.(slotFromEvent(e, c)); }}
                onDragOver={(e) => { if (onMove && drag.current) e.preventDefault(); }}
                onDrop={(e) => {
                  const moving = appointments.find((a) => a.id === drag.current?.id);
                  if (moving && onMove) { e.preventDefault(); onMove(moving, slotFromEvent(e, c, drag.current?.grab ?? 0)); }
                  drag.current = null;
                }}
              >
                {workingStretches(c.resource.hours, c.day).map((w) => {
                  const p = place(w.start, w.end, range);
                  return <div key={`${w.start}-${w.end}`} data-slot="1" className="absolute inset-x-0 bg-surface" style={{ top: `${p.top}%`, height: `${p.height}%` }} />;
                })}
                {hours.map((h, i) => i > 0 && <div key={h} className="pointer-events-none absolute inset-x-0 border-t border-line/60" style={{ top: i * HOUR_PX }} />)}
                {off(c).map((o) => {
                  const p = place(o.start, o.end, range);
                  return <div key={`off-${o.start}`} className="pointer-events-none absolute inset-x-0 bg-bad-soft/60" style={{ top: `${p.top}%`, height: `${p.height}%` }} title={t("calendar.timeOff")} />;
                })}
                {inColumn(c).map((a) => {
                  const p = place(minutesOfDay(a.starts_at, zone), minutesOfDay(a.ends_at, zone) || 24 * 60, range);
                  const status: Status = isStatus(a.status) ? a.status : "confirmed";
                  const movable = !!onMove && MOVABLE.includes(a.status);
                  return (
                    <button
                      key={a.id} type="button" draggable={movable}
                      aria-label={`${clock(a.starts_at, zone)} ${a.client_name ?? ""} ${a.service} ${t(`status.${a.status}`)}`}
                      className={cx("absolute inset-x-1 overflow-hidden rounded-md border-l-4 px-1.5 py-0.5 text-left text-xs leading-tight shadow-card focus:outline-none focus-visible:ring-2 focus-visible:ring-brand", BLOCK_CLASS[status], movable && "cursor-grab")}
                      style={{ top: `${p.top}%`, height: `${p.height}%` }}
                      onClick={(e) => { e.stopPropagation(); onOpen?.(a); }} onKeyDown={(e) => onKey(e, a)}
                      onDragStart={(e) => {
                        const rect = e.currentTarget.getBoundingClientRect();
                        drag.current = { id: a.id, grab: Math.floor(((e.clientY - rect.top) / HOUR_PX) * 60 / 15) * 15 };
                        e.dataTransfer.effectAllowed = "move";
                      }}
                      onDragEnd={() => { drag.current = null; }}
                    >
                      <span className="block truncate font-medium">{clock(a.starts_at, zone)} {a.kind === "class" ? `${a.service} (${a.attendees}/${a.capacity})` : a.client_name}</span>
                      <span className="block truncate opacity-80">{a.kind === "class" ? "" : a.service}</span>
                    </button>
                  );
                })}
                {c.day === today && nowMin >= range.start && nowMin <= range.end && (
                  <div className="pointer-events-none absolute inset-x-0 z-10 border-t-2 border-bad" style={{ top: `${((nowMin - range.start) / (range.end - range.start)) * 100}%` }} aria-hidden>
                    <span className="absolute -left-1 -top-[5px] h-2 w-2 rounded-full bg-bad" />
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      <Agenda columns={columns} appointments={appointments} zone={zone} view={view} onOpen={onOpen} />
      <Legend />
    </div>
  );
}

/** The phone layout: the same appointments as a list, grouped by person (day view) or by day (week view). */
function Agenda({ columns, appointments, zone, view, onOpen }: { columns: Column[]; appointments: Appointment[]; zone?: string; view: "day" | "week"; onOpen?: (a: Appointment) => void }) {
  const { t } = useTranslation("bookings");
  const groups = columns.map((c) => ({ c, rows: appointments.filter((a) => a.resource_ids.includes(c.resource.id) && dayOf(a.starts_at, zone) === c.day).sort((x, y) => x.starts_at.localeCompare(y.starts_at)) }));
  const shown = view === "week" ? groups.filter((g) => g.rows.length > 0) : groups;
  if (shown.every((g) => g.rows.length === 0)) return <p className="rounded-xl border border-dashed border-line p-6 text-center text-sm text-muted md:hidden">{t("calendar.agendaEmpty")}</p>;
  return (
    <div className="space-y-4 md:hidden">
      {shown.map(({ c, rows }) => (
        <section key={c.key} aria-label={c.title}>
          <h3 className="mb-1 text-sm font-semibold">{c.title}{c.subtitle && <span className="ml-2 font-normal text-muted">{c.subtitle}</span>}</h3>
          {rows.length === 0 ? <p className="text-sm text-muted">{t("calendar.agendaNone")}</p> : (
            <ul className="space-y-1.5">
              {rows.map((a) => {
                const status: Status = isStatus(a.status) ? a.status : "confirmed";
                return (
                  <li key={a.id}>
                    <button type="button" onClick={() => onOpen?.(a)} className={cx("flex w-full items-center gap-3 rounded-lg border-l-4 px-3 py-2 text-left text-sm", BLOCK_CLASS[status])}>
                      <span className="w-12 shrink-0 font-medium">{clock(a.starts_at, zone)}</span>
                      <span className="min-w-0 flex-1"><span className="block truncate font-medium">{a.kind === "class" ? a.service : a.client_name}</span><span className="block truncate text-xs opacity-80">{a.kind === "class" ? `${a.attendees}/${a.capacity}` : a.service}</span></span>
                      <span className="text-xs">{t(`status.${a.status}`)}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      ))}
    </div>
  );
}

/** What each colour means. */
export function Legend() {
  const { t } = useTranslation("bookings");
  return (
    <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-muted" aria-label={t("calendar.legend")}>
      {STATUSES.filter((s) => s !== "cancelled").map((s) => (
        <li key={s} className="flex items-center gap-1.5"><span className={cx("inline-block h-3 w-3 rounded-sm border-l-4", BLOCK_CLASS[s])} />{t(`status.${s}`)}</li>
      ))}
      <li className="flex items-center gap-1.5"><span className="inline-block h-3 w-3 rounded-sm bg-bad-soft" />{t("calendar.timeOff")}</li>
      <li className="flex items-center gap-1.5"><span className="inline-block h-3 w-3 rounded-sm border border-line bg-sunken" />{t("calendar.closed")}</li>
    </ul>
  );
}
