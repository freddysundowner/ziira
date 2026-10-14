import { type FormEvent } from "react";

import { api, Button, Drawer, Field, FormGrid, Input, NumberInput, Select, toast, today, unwrap, useFormState, useMutation, useQueryClient, useTranslation } from "@/sdk";

import { useShifts } from "../lib/lookups";
import { fromLocalInput, toLocalInput } from "../lib/time";
import type { Attendance } from "../lib/types";
import { EmployeePicker } from "./EmployeePicker";

/** Record a day worked by hand, or correct a recorded day. */
export function AttendanceDrawer({ open, onClose, companyId, employeeId, record }: { open: boolean; onClose: () => void; companyId: string; employeeId?: string; record?: Attendance }) {
  return open ? <Body onClose={onClose} companyId={companyId} employeeId={employeeId} record={record} /> : null;
}

function Body({ onClose, companyId, employeeId, record }: { onClose: () => void; companyId: string; employeeId?: string; record?: Attendance }) {
  const { t } = useTranslation("people");
  const qc = useQueryClient();
  const shifts = useShifts(companyId);
  const f = useFormState({
    employee_id: record?.employee_id ?? employeeId ?? "", work_date: record?.work_date ?? today(), clock_in: toLocalInput(record?.clock_in),
    clock_out: toLocalInput(record?.clock_out), hours: record?.hours ?? "", overtime_hours: record && Number(record.overtime_hours) > 0 ? record.overtime_hours : "", shift_id: record?.shift_id ?? "",
  });
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => {
      const v = f.values;
      const times = { clock_in: fromLocalInput(v.clock_in), clock_out: fromLocalInput(v.clock_out), hours: v.hours || null, overtime_hours: v.overtime_hours || null };
      if (record) return unwrap(api.PATCH("/api/v1/people/attendance/{attendance_id}", { params: { path: { attendance_id: record.id } }, body: times }));
      return unwrap(api.POST("/api/v1/people/attendance", { body: { employee_id: v.employee_id, work_date: v.work_date, shift_id: v.shift_id || null, ...times } }));
    },
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["people"] }); toast(t("attendance.saved"), "ok"); onClose(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };

  return (
    <Drawer open onClose={onClose} title={record ? t("attendance.edit") : t("attendance.new")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="attendance-form" loading={save.isPending} disabled={!f.values.employee_id}>{t("save")}</Button></>}>
      <form id="attendance-form" onSubmit={submit} className="space-y-4">
        {!record && !employeeId && (
          <Field label={t("attendance.employee")} required error={f.error("employee_id")}>
            <EmployeePicker companyId={companyId} value={f.values.employee_id} onChange={(id) => f.set("employee_id", id)} activeOnly />
          </Field>
        )}
        <Field label={t("attendance.date")} required error={f.error("work_date")}><Input type="date" {...f.bind("work_date")} required disabled={!!record} /></Field>
        {!record && (shifts.data ?? []).length > 0 && (
          <Field label={t("attendance.shift")} hint={t("attendance.shiftHint")}>
            <Select {...f.bind("shift_id")}><option value="">{t("none")}</option>{(shifts.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.name} · {s.start_time.slice(0, 5)}–{s.end_time.slice(0, 5)}</option>)}</Select>
          </Field>
        )}
        <FormGrid>
          <Field label={t("attendance.clockIn")} error={f.error("clock_in")}><Input type="datetime-local" {...f.bind("clock_in")} /></Field>
          <Field label={t("attendance.clockOut")} error={f.error("clock_out")}><Input type="datetime-local" {...f.bind("clock_out")} /></Field>
          <Field label={t("attendance.hours")} hint={t("attendance.hoursHint")} error={f.error("hours")}><NumberInput value={f.values.hours} onChange={(v) => f.set("hours", v)} /></Field>
          <Field label={t("attendance.overtime")} hint={t("attendance.overtimeHint")} error={f.error("overtime_hours")}><NumberInput value={f.values.overtime_hours} onChange={(v) => f.set("overtime_hours", v)} /></Field>
        </FormGrid>
      </form>
    </Drawer>
  );
}
