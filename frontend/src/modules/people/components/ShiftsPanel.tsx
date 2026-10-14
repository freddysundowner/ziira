import { Plus } from "lucide-react";
import { type FormEvent, useState } from "react";

import { api, Button, DataTable, Drawer, Field, FormGrid, Input, Select, toast, unwrap, useCan, useFormState, useMutation, useQueryClient, useTranslation } from "@/sdk";

import { useShifts } from "../lib/lookups";
import { shortTime } from "../lib/time";

export function ShiftsPanel({ companyId, branches }: { companyId: string; branches: { id: string; name: string }[] }) {
  const { t } = useTranslation("people");
  const canManage = useCan("attendance.manage");
  const [adding, setAdding] = useState(false);
  const shifts = useShifts(companyId);
  const add = canManage ? <Button onClick={() => setAdding(true)}><Plus className="h-4 w-4" />{t("shift.new")}</Button> : undefined;
  return (
    <>
      <DataTable
        rows={shifts.data} loading={shifts.isLoading} error={shifts.error?.message} onRetry={() => void shifts.refetch()} rowKey={(s) => s.id}
        toolbar={add && <div className="ml-auto">{add}</div>}
        empty={{ title: t("shift.empty"), hint: t("shift.emptyHint"), action: add }}
        columns={[
          { header: t("shift.name"), cell: (s) => <span className="font-medium">{s.name}</span> },
          { header: t("shift.start"), cell: (s) => shortTime(s.start_time) },
          { header: t("shift.end"), cell: (s) => shortTime(s.end_time) },
          { header: t("branch"), hideBelow: "sm", cell: (s) => (s.branch_id ? branches.find((b) => b.id === s.branch_id)?.name ?? "—" : t("allBranches")) },
        ]}
      />
      {adding && <NewShift onClose={() => setAdding(false)} companyId={companyId} branches={branches} />}
    </>
  );
}

function NewShift({ onClose, companyId, branches }: { onClose: () => void; companyId: string; branches: { id: string; name: string }[] }) {
  const { t } = useTranslation("people");
  const qc = useQueryClient();
  const f = useFormState({ name: "", start_time: "08:00", end_time: "17:00", branch_id: "" });
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/people/shifts", { body: { company_id: companyId, name: f.values.name.trim(), start_time: f.values.start_time, end_time: f.values.end_time, branch_id: f.values.branch_id || null } })),
    onSuccess: (s) => { void qc.invalidateQueries({ queryKey: ["people", "shifts"] }); toast(t("shift.created", { name: s.name }), "ok"); onClose(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  return (
    <Drawer open onClose={onClose} title={t("shift.new")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="shift-form" loading={save.isPending}>{t("save")}</Button></>}>
      <form id="shift-form" onSubmit={submit} className="space-y-4">
        <Field label={t("shift.name")} required error={f.error("name")}><Input {...f.bind("name")} required autoFocus maxLength={60} /></Field>
        <FormGrid>
          <Field label={t("shift.start")} required error={f.error("start_time")}><Input type="time" {...f.bind("start_time")} required /></Field>
          <Field label={t("shift.end")} required error={f.error("end_time")} hint={t("shift.endHint")}><Input type="time" {...f.bind("end_time")} required /></Field>
        </FormGrid>
        {branches.length > 1 && (
          <Field label={t("branch")} error={f.error("branch_id")}>
            <Select {...f.bind("branch_id")}><option value="">{t("allBranches")}</option>{branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</Select>
          </Field>
        )}
      </form>
    </Drawer>
  );
}
