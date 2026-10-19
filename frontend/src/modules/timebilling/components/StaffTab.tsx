import { type FormEvent, useEffect, useState } from "react";

import { api, Badge, Button, DataTable, Drawer, Field, Input, Select, toast, unwrap, useCan, useFormState, useMutation, useTranslation } from "@/sdk";

import { useRefresh, useStaff } from "../hooks";
import { formatClock, formatDuration, parseDuration } from "../lib";
import type { Staff } from "../types";

/** Each person's job title (used by role rates) and how many hours a week they are expected to work. */
export function StaffTab({ companyId }: { companyId: string }) {
  const { t } = useTranslation("timebilling");
  const canManage = useCan("projects.manage");
  const canSettings = useCan("time.settings");
  const canEdit = canManage || canSettings;
  const staff = useStaff(companyId);
  const [editing, setEditing] = useState<Staff | null>(null);
  return (
    <>
      <p className="mb-3 text-sm text-muted">{t("staff.hint")}</p>
      <DataTable
        rows={staff.data} loading={staff.isLoading} error={staff.error?.message} onRetry={() => void staff.refetch()} rowKey={(s) => s.user_id}
        searchText={(s) => `${s.name} ${s.title ?? ""}`}
        empty={{ title: t("staff.empty") }}
        columns={[
          { header: t("staff.name"), sortValue: (s) => s.name, cell: (s) => <span><span className="font-medium">{s.name}</span>{s.email && <span className="block text-xs text-muted">{s.email}</span>}</span> },
          { header: t("rates.role"), cell: (s) => s.title ?? <span className="text-muted">—</span> },
          { header: t("staff.capacity"), align: "right", hideBelow: "sm", cell: (s) => (s.weekly_capacity_minutes === null ? <span className="text-muted">{t("staff.businessDefault")}</span> : <span className="tnum">{formatDuration(s.weekly_capacity_minutes)}</span>) },
          { header: t("status"), hideBelow: "md", cell: (s) => <Badge tone={s.active ? "ok" : "neutral"}>{t(s.active ? "staff.active" : "staff.inactive")}</Badge> },
          { header: "", align: "right", cell: (s) => canEdit && <Button size="sm" variant="ghost" onClick={() => setEditing(s)}>{t("edit")}</Button> },
        ]} />
      <StaffDrawer person={editing} companyId={companyId} onClose={() => setEditing(null)} />
    </>
  );
}

function StaffDrawer({ person, companyId, onClose }: { person: Staff | null; companyId: string; onClose: () => void }) {
  const { t } = useTranslation("timebilling");
  const refresh = useRefresh();
  const f = useFormState({ title: "", capacity: "", approver: "", away: "" });
  const [active, setActive] = useState(true);
  const [nudges, setNudges] = useState(true);
  const people = useStaff(companyId);
  const { reset, set } = f;
  useEffect(() => {
    if (!person) return;
    reset();
    set("title", person.title ?? "");
    set("capacity", person.weekly_capacity_minutes === null ? "" : formatClock(person.weekly_capacity_minutes));
    setActive(person.active);
    setNudges(person.nudges);
    set("approver", person.approver_id ?? "");
    set("away", person.away_until ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [person?.user_id]);
  const capacity = parseDuration(f.values.capacity, 10080);
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.PUT("/api/v1/timebilling/staff/{user_id}", { params: { path: { user_id: person!.user_id } }, body: {
      company_id: companyId, title: f.values.title.trim() || null, weekly_capacity_minutes: f.values.capacity === "" ? null : capacity, active,
      approver_id: f.values.approver || null, away_until: f.values.away || null, nudges } })),
    onSuccess: () => { void refresh(); toast(t("staff.saved"), "ok"); onClose(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  return (
    <Drawer open={!!person} onClose={onClose} title={person?.name ?? ""}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="staff-form" loading={save.isPending} disabled={f.values.capacity !== "" && capacity === null}>{t("save")}</Button></>}>
      <form id="staff-form" onSubmit={submit} className="space-y-4">
        <Field label={t("rates.role")} hint={t("staff.titleHint")} error={f.error("title")}><Input {...f.bind("title")} maxLength={80} /></Field>
        <Field label={t("staff.capacity")} hint={t("staff.capacityHint")} error={f.error("weekly_capacity_minutes") ?? (f.values.capacity !== "" && capacity === null ? t("timeInvalid") : null)}><Input {...f.bind("capacity")} placeholder="40:00" /></Field>
        <Field label={t("staff.approver")} hint={t("staff.approverHint")} error={f.error("approver_id")}>
          <Select {...f.bind("approver")}><option value="">{t("staff.anyApprover")}</option>{(people.data ?? []).filter((x) => x.user_id !== person?.user_id && x.active).map((x) => <option key={x.user_id} value={x.user_id}>{x.name}</option>)}</Select>
        </Field>
        <Field label={t("staff.away")} hint={t("staff.awayHint")} error={f.error("away_until")}><Input type="date" {...f.bind("away")} /></Field>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="h-4 w-4 accent-[rgb(var(--brand))]" checked={nudges} onChange={(e) => setNudges(e.target.checked)} />{t("staff.reminders")}</label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="h-4 w-4 accent-[rgb(var(--brand))]" checked={active} onChange={(e) => setActive(e.target.checked)} />{t("staff.countsInReports")}</label>
      </form>
    </Drawer>
  );
}
