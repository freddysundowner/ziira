import { type FormEvent, useEffect, useState } from "react";

import {
  Alert, api, Button, Checkbox, Drawer, Field, FormGrid, Input, Select, toast, unwrap, useMutation, useQuery, useTranslation,
} from "@/sdk";

import { useBranch, useRefreshBookings } from "../hooks";
import { dayOf, parseWindows, windowsText, zonedIso } from "../lib";
import type { Resource } from "../types";

const WEEK = [0, 1, 2, 3, 4, 5, 6] as const;
const DEFAULT_HOURS = ["09:00-17:00", "09:00-17:00", "09:00-17:00", "09:00-17:00", "09:00-17:00", "", ""];

function hoursOf(resource?: Resource): string[] {
  return resource ? WEEK.map((d) => windowsText(resource.hours, d)) : DEFAULT_HOURS;
}

/** Add or edit a person, room, chair or machine: its details, weekly hours and (when it exists) time off. */
export function ResourceForm({ open, onClose, resource }: { open: boolean; onClose: () => void; resource?: Resource }) {
  const { t } = useTranslation("bookings");
  const refresh = useRefreshBookings();
  const { companyId, branches, branchId } = useBranch();
  const [name, setName] = useState("");
  const [kind, setKind] = useState("staff");
  const [branch, setBranch] = useState("");
  const [colour, setColour] = useState("");
  const [level, setLevel] = useState("");
  const [publicly, setPublicly] = useState(true);
  const [active, setActive] = useState(true);
  const [hours, setHours] = useState<string[]>(DEFAULT_HOURS);
  const [bad, setBad] = useState<number | null>(null);
  useEffect(() => {
    if (!open) return;
    setName(resource?.name ?? ""); setKind(resource?.kind ?? "staff"); setBranch(resource?.branch_id ?? branchId); setColour(resource?.colour ?? ""); setLevel(resource?.level ?? "");
    setPublicly(resource?.show_publicly ?? true); setActive(resource?.is_active ?? true); setHours(hoursOf(resource)); setBad(null);
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = useMutation({
    meta: { silent: true },
    mutationFn: async () => {
      const windows = hours.map((h) => parseWindows(h));
      const wrong = windows.findIndex((w) => w === null);
      if (wrong >= 0) { setBad(wrong); throw new Error(t("resources.badHours")); }
      const rows = windows.flatMap((w, weekday) => (w ?? []).map((x) => ({ weekday, ...x })));
      if (resource) {
        await unwrap(api.PATCH("/api/v1/bookings/resources/{resource_id}", { params: { path: { resource_id: resource.id } }, body: {
          name: name.trim(), kind: kind as "staff", colour: colour || null, show_publicly: publicly, is_active: active, level: level.trim() || null } }));
        await unwrap(api.PUT("/api/v1/bookings/resources/{resource_id}/hours", { params: { path: { resource_id: resource.id } }, body: rows }));
        return;
      }
      await unwrap(api.POST("/api/v1/bookings/resources", { body: {
        company_id: companyId, branch_id: branch, name: name.trim(), kind: kind as "staff", colour: colour || null, show_publicly: publicly, sort_order: 0, level: level.trim() || null, hours: rows } }));
    },
    onSuccess: () => { void refresh(); toast(t(resource ? "resources.updated" : "resources.created"), "ok"); onClose(); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };

  return (
    <Drawer open={open} onClose={onClose} title={resource ? t("resources.edit") : t("resources.new")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("close")}</Button><Button type="submit" form="resource-form" loading={save.isPending} disabled={!name.trim()}>{t("save")}</Button></>}>
      <form id="resource-form" onSubmit={submit} className="space-y-4">
        <Field label={t("resources.name")} required hint={t("resources.nameHint")}><Input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} autoFocus /></Field>
        <FormGrid>
          <Field label={t("resources.kind")}>
            <Select value={kind} onChange={(e) => setKind(e.target.value)}>
              {(["staff", "room", "chair", "equipment"] as const).map((k) => <option key={k} value={k}>{t(`kinds.${k}`)}</option>)}
            </Select>
          </Field>
          {!resource && branches.length > 1 && (
            <Field label={t("branch")}><Select value={branch} onChange={(e) => setBranch(e.target.value)}>{branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</Select></Field>
          )}
          {(kind === "staff" || kind === "chair") && <Field label={t("resources.level")} hint={t("resources.levelHint")}><Input value={level} onChange={(e) => setLevel(e.target.value)} maxLength={40} placeholder={t("resources.levelExample")} /></Field>}
          <Field label={t("resources.colour")} hint={t("resources.colourHint")}><Input type="color" value={colour || "#1a73e8"} onChange={(e) => setColour(e.target.value)} className="h-9 p-1" /></Field>
        </FormGrid>
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">{t("resources.hours")}</legend>
          <p className="text-xs text-muted">{t("resources.hoursHint")}</p>
          {WEEK.map((d) => (
            <div key={d} className="grid grid-cols-[6.5rem_1fr] items-center gap-2">
              <label htmlFor={`hours-${d}`} className="text-sm">{t(`weekdays.${d}`)}</label>
              <Input id={`hours-${d}`} value={hours[d]} placeholder={t("resources.closed")} invalid={bad === d}
                onChange={(e) => { const next = [...hours]; next[d] = e.target.value; setHours(next); if (bad === d) setBad(null); }} />
            </div>
          ))}
        </fieldset>
        <Checkbox checked={publicly} onChange={(e) => setPublicly(e.target.checked)} label={t("resources.showPublicly")} />
        {resource && <Checkbox checked={active} onChange={(e) => setActive(e.target.checked)} label={t("resources.active")} />}
        {resource && <TimeOffPanel resource={resource} />}
      </form>
    </Drawer>
  );
}

/** Leave, repairs, a course: periods when the resource cannot be booked. */
function TimeOffPanel({ resource }: { resource: Resource }) {
  const { t } = useTranslation("bookings");
  const refresh = useRefreshBookings();
  const { zone } = useBranch();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [reason, setReason] = useState("");
  const [affected, setAffected] = useState<number | null>(null);
  const list = useQuery({
    queryKey: ["bookings", "time-off", resource.id],
    queryFn: () => unwrap(api.GET("/api/v1/bookings/resources/{resource_id}/time-off", { params: { path: { resource_id: resource.id }, query: { start: new Date().toISOString() } } })),
  });
  const iso = (value: string) => zonedIso(value.slice(0, 10), value.slice(11, 16), zone);
  const add = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/bookings/resources/{resource_id}/time-off", { params: { path: { resource_id: resource.id } }, body: { starts_at: iso(from), ends_at: iso(to), reason: reason.trim() || null } })),
    onSuccess: (row) => { setAffected(row.affected_appointments); setFrom(""); setTo(""); setReason(""); void list.refetch(); void refresh(); },
  });
  const remove = useMutation({
    mutationFn: (id: string) => unwrap(api.DELETE("/api/v1/bookings/time-off/{time_off_id}", { params: { path: { time_off_id: id } } })),
    onSuccess: () => { void list.refetch(); void refresh(); },
  });
  return (
    <section className="space-y-3 border-t border-line pt-4" aria-label={t("resources.timeOff")}>
      <h3 className="text-sm font-semibold">{t("resources.timeOff")}</h3>
      {affected !== null && affected > 0 && <Alert tone="warn">{t("resources.timeOffAffected", { count: affected })}</Alert>}
      {(list.data ?? []).length === 0 && !list.isLoading && <p className="text-sm text-muted">{t("resources.noTimeOff")}</p>}
      <ul className="divide-y divide-line">
        {(list.data ?? []).map((o) => (
          <li key={o.id} className="flex items-center justify-between gap-2 py-2 text-sm">
            <span>{dayOf(o.starts_at, zone)} → {dayOf(o.ends_at, zone)}{o.reason ? ` · ${o.reason}` : ""}</span>
            <Button size="sm" variant="ghost" loading={remove.isPending && remove.variables === o.id} onClick={() => remove.mutate(o.id)}>{t("drawer.remove")}</Button>
          </li>
        ))}
      </ul>
      <FormGrid>
        <Field label={t("resources.offFrom")}><Input type="datetime-local" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
        <Field label={t("resources.offTo")}><Input type="datetime-local" value={to} min={from} onChange={(e) => setTo(e.target.value)} /></Field>
      </FormGrid>
      <Field label={t("resources.offReason")}><Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={200} /></Field>
      <Button variant="secondary" disabled={!from || !to || to <= from} loading={add.isPending} onClick={() => add.mutate()}>{t("resources.addTimeOff")}</Button>
    </section>
  );
}
