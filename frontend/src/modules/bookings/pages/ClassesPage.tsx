import { ChevronLeft, ChevronRight, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import {
  api, Badge, Button, Card, EmptyState, ErrorState, Field, formatDate, FormGrid, IconButton, Input, PageHeader, Select, SkeletonRows, toast, today, unwrap, useCan, useMutation, useQuery, useTranslation,
} from "@/sdk";

import { AddClassDrawer } from "../components/AddClassDrawer";
import { BranchPicker } from "../components/BranchBar";
import { SessionDrawer } from "../components/SessionDrawer";
import { useBranch, useRefreshBookings, useResources } from "../hooks";
import { addDays, clock, weekdayOf } from "../lib";
import { groupByDay, weekBounds } from "../ops/logic";
import type { ClassSession } from "../types";

export default function ClassesPage() {
  const { t } = useTranslation("bookings");
  const canManage = useCan("bookings.manage");
  const { branches, branchId, setBranchId, companyId, zone } = useBranch();
  const [day, setDay] = useState(today());
  const [adding, setAdding] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const week = weekBounds(day, zone);
  const resources = useResources(branchId, false);
  const list = useQuery<ClassSession[]>({
    queryKey: ["bookings", "sessions", branchId, week.startIso],
    enabled: !!branchId,
    queryFn: () => unwrap(api.GET("/api/v1/bookings/sessions", { params: { query: { branch_id: branchId, start: week.startIso, end: week.endIso } } })),
  });
  const people = (ids: string[]) => ids.map((id) => resources.data?.find((r) => r.id === id)?.name).filter(Boolean).join(", ");
  const groups = groupByDay(list.data ?? [], zone);

  return (
    <>
      <PageHeader title={t("classes.title")} description={t("classes.hint")}
        actions={<><BranchPicker branches={branches} value={branchId} onChange={setBranchId} />{canManage && <Button onClick={() => setAdding(true)}><Plus className="h-4 w-4" />{t("classes.add")}</Button>}</>} />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <IconButton label={t("classes.prevWeek")} onClick={() => setDay(addDays(week.first, -7))}><ChevronLeft className="h-4 w-4" /></IconButton>
        <p className="min-w-0 flex-1 text-center text-sm font-semibold sm:flex-none sm:px-3">{formatDate(week.first)} – {formatDate(week.last)}</p>
        <IconButton label={t("classes.nextWeek")} onClick={() => setDay(addDays(week.first, 7))}><ChevronRight className="h-4 w-4" /></IconButton>
        <Button variant="secondary" size="sm" onClick={() => setDay(today())}>{t("classes.thisWeek")}</Button>
      </div>

      <Card flush>
        {list.isLoading && <SkeletonRows rows={5} cols={4} />}
        {list.error && <ErrorState message={list.error.message} onRetry={() => void list.refetch()} />}
        {list.data && groups.length === 0 && (
          <EmptyState title={t("classes.empty")} hint={t("classes.emptyHint")} action={canManage ? <Button onClick={() => setAdding(true)}>{t("classes.add")}</Button> : undefined} />
        )}
        {groups.map((g) => (
          <section key={g.day} aria-label={formatDate(g.day)} className="border-b border-line last:border-b-0">
            <h2 className="bg-sunken px-4 py-2 text-xs font-bold uppercase tracking-wide text-muted sm:px-5">{t(`weekdays.${weekdayOf(g.day)}`)} · {formatDate(g.day)}</h2>
            <ul>
              {g.rows.map((s) => (
                <li key={s.id}>
                  <button type="button" onClick={() => setOpen(s.id)} className="flex min-h-[56px] w-full items-center gap-3 px-4 py-3 text-left hover:bg-sunken focus-visible:bg-sunken sm:px-5">
                    <span className="tnum w-14 shrink-0 text-sm font-semibold">{clock(s.starts_at, zone)}</span>
                    <span className="min-w-0 flex-1">
                      <span className={`block truncate font-medium ${s.status === "cancelled" ? "text-muted line-through" : ""}`}>{s.name}</span>
                      <span className="block truncate text-xs text-muted">{people(s.resource_ids) || t("classes.noInstructor")}</span>
                    </span>
                    {s.status === "cancelled"
                      ? <Badge tone="neutral">{t("classes.cancelledBadge")}</Badge>
                      : <span className="flex flex-col items-end gap-1 sm:flex-row sm:items-center">
                          <Badge tone={s.free === 0 ? "warn" : "ok"}>{t("classes.places", { booked: s.booked, capacity: s.capacity })}</Badge>
                          {s.waiting > 0 && <Badge tone="info">{t("classes.waiting", { count: s.waiting })}</Badge>}
                        </span>}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </Card>

      <ClosedDays companyId={companyId} branchId={branchId} branches={branches} />

      <AddClassDrawer open={adding} onClose={() => setAdding(false)} companyId={companyId} branchId={branchId} day={day} zone={zone} />
      <SessionDrawer sessionId={open} companyId={companyId} zone={zone} onClose={() => setOpen(null)} />
    </>
  );
}

/** Days the business is shut (no class is scheduled on them). */
function ClosedDays({ companyId, branchId, branches }: { companyId: string; branchId: string; branches: { id: string; name: string }[] }) {
  const { t } = useTranslation("bookings");
  const canSetup = useCan("bookings.setup");
  const refresh = useRefreshBookings();
  const [day, setDay] = useState("");
  const [label, setLabel] = useState("");
  const [scope, setScope] = useState("all");
  const list = useQuery({
    queryKey: ["bookings", "closed-days", companyId], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/bookings/closed-days", { params: { query: { company_id: companyId, start: today() } } })),
  });
  const add = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/bookings/closed-days", { body: { company_id: companyId, day, label: label.trim() || null, branch_id: scope === "all" ? null : branchId } })),
    onSuccess: () => { void refresh(); setDay(""); setLabel(""); toast(t("classes.closedAdded"), "ok"); },
  });
  const remove = useMutation({
    mutationFn: (id: string) => unwrap(api.DELETE("/api/v1/bookings/closed-days/{closed_id}", { params: { path: { closed_id: id } } })),
    onSuccess: () => { void refresh(); toast(t("classes.closedRemoved"), "ok"); },
  });
  const branchName = (id: string | null) => (id ? branches.find((b) => b.id === id)?.name ?? "" : t("classes.allBranches"));

  return (
    <Card className="mt-6" title={t("classes.closedTitle")} description={t("classes.closedHint")}>
      {list.isLoading && <SkeletonRows rows={2} cols={3} />}
      {list.error && <ErrorState message={list.error.message} onRetry={() => void list.refetch()} />}
      {list.data && list.data.length === 0 && <p className="text-sm text-muted">{t("classes.closedEmpty")}</p>}
      <ul className="divide-y divide-line">
        {(list.data ?? []).map((c) => (
          <li key={c.id} className="flex min-h-[48px] items-center justify-between gap-3 py-2">
            <div className="min-w-0 text-sm">
              <p className="font-medium">{formatDate(c.day)}{c.label ? ` · ${c.label}` : ""}</p>
              {branches.length > 1 && <p className="text-xs text-muted">{branchName(c.branch_id)}</p>}
            </div>
            {canSetup && <IconButton label={t("classes.closedRemove")} disabled={remove.isPending && remove.variables === c.id} onClick={() => remove.mutate(c.id)}><Trash2 className="h-4 w-4" /></IconButton>}
          </li>
        ))}
      </ul>
      {canSetup && (
        <form className="mt-4 space-y-3 border-t border-line pt-4" onSubmit={(e) => { e.preventDefault(); if (day) add.mutate(); }}>
          <FormGrid>
            <Field label={t("form.date")} required><Input type="date" value={day} min={today()} onChange={(e) => setDay(e.target.value)} /></Field>
            <Field label={t("classes.closedLabel")}><Input value={label} maxLength={100} onChange={(e) => setLabel(e.target.value)} /></Field>
          </FormGrid>
          {branches.length > 1 && (
            <Field label={t("classes.closedFor")}>
              <Select value={scope} onChange={(e) => setScope(e.target.value)}>
                <option value="all">{t("classes.allBranches")}</option>
                <option value="this">{branchName(branchId)}</option>
              </Select>
            </Field>
          )}
          <Button type="submit" disabled={!day} loading={add.isPending}>{t("classes.closedAdd")}</Button>
        </form>
      )}
    </Card>
  );
}
