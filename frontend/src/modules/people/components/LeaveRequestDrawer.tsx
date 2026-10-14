import { type FormEvent } from "react";

import { api, Button, Drawer, Field, FormGrid, Input, NumberInput, Select, toast, today, unwrap, useFormState, useMutation, useQueryClient, useTranslation, orNull } from "@/sdk";

import { useLeaveTypes } from "../lib/lookups";
import { EmployeePicker } from "./EmployeePicker";

/** Ask for leave for an employee (or, with the picker cleared, for yourself). */
export function LeaveRequestDrawer({ open, onClose, companyId, employeeId }: { open: boolean; onClose: () => void; companyId: string; employeeId?: string }) {
  return open ? <Body onClose={onClose} companyId={companyId} employeeId={employeeId} /> : null;
}

function Body({ onClose, companyId, employeeId }: { onClose: () => void; companyId: string; employeeId?: string }) {
  const { t } = useTranslation("people");
  const qc = useQueryClient();
  const types = useLeaveTypes(companyId);
  const f = useFormState({ employee_id: employeeId ?? "", leave_type_id: "", start_date: today(), end_date: today(), days: "", reason: "" });
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/people/leave-requests", { body: {
      employee_id: f.values.employee_id || null, leave_type_id: f.values.leave_type_id || types.data?.[0]?.id || "", start_date: f.values.start_date,
      end_date: f.values.end_date, days: orNull(f.values.days), reason: orNull(f.values.reason) } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["people"] }); toast(t("leave.requested"), "ok"); onClose(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  const noTypes = types.isSuccess && types.data.length === 0;

  return (
    <Drawer open onClose={onClose} title={t("leave.new")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="leave-form" loading={save.isPending} disabled={noTypes}>{t("leave.submit")}</Button></>}>
      <form id="leave-form" onSubmit={submit} className="space-y-4">
        {noTypes && <p className="rounded-lg bg-warn-soft px-3 py-2 text-sm text-warn">{t("leave.needTypes")}</p>}
        {!employeeId && (
          <Field label={t("leave.employee")} hint={t("leave.employeeHint")} error={f.error("employee_id")}>
            <EmployeePicker companyId={companyId} value={f.values.employee_id} onChange={(id) => f.set("employee_id", id)} placeholder={t("leave.myself")} activeOnly />
          </Field>
        )}
        <Field label={t("leave.type")} required error={f.error("leave_type_id")}>
          <Select {...f.bind("leave_type_id")}>{(types.data ?? []).map((x) => <option key={x.id} value={x.id}>{x.name}{x.is_paid ? "" : ` · ${t("leave.unpaid")}`}</option>)}</Select>
        </Field>
        <FormGrid>
          <Field label={t("leave.from")} required error={f.error("start_date")}><Input type="date" {...f.bind("start_date")} required /></Field>
          <Field label={t("leave.to")} required error={f.error("end_date")}><Input type="date" min={f.values.start_date} {...f.bind("end_date")} required /></Field>
        </FormGrid>
        <Field label={t("leave.days")} hint={t("leave.daysHint")} error={f.error("days")}><NumberInput value={f.values.days} onChange={(v) => f.set("days", v)} /></Field>
        <Field label={t("leave.reason")} error={f.error("reason")}><Input {...f.bind("reason")} maxLength={300} /></Field>
      </form>
    </Drawer>
  );
}
