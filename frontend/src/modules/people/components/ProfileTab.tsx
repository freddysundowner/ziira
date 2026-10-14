import { Pencil, UserMinus } from "lucide-react";
import { useState } from "react";

import { api, Button, Card, DetailList, Field, formatDate, Input, Modal, toast, today, unwrap, useCan, useMutation, useQueryClient, useTranslation } from "@/sdk";

import { useDepartments, useRules } from "../lib/lookups";
import type { Employee } from "../lib/types";
import { EmployeeDrawer } from "./EmployeeDrawer";

export function ProfileTab({ employee, branchName }: { employee: Employee; branchName: string }) {
  const { t } = useTranslation("people");
  const canManage = useCan("employees.manage");
  const [editing, setEditing] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const departments = useDepartments(employee.company_id);
  const rules = useRules(employee.company_id);
  const ruleName = (code: string) => String((rules.data?.find((r) => r.code === code)?.definition as { name?: string } | undefined)?.name ?? code);
  const registrations = Object.entries(employee.registrations);

  return (
    <div className="space-y-4">
      <Card title={t("employee.details")} actions={canManage && employee.status !== "terminated" && <>
        <Button size="sm" variant="secondary" onClick={() => setEditing(true)}><Pencil className="h-3.5 w-3.5" />{t("edit")}</Button>
        <Button size="sm" variant="secondary" onClick={() => setLeaving(true)}><UserMinus className="h-3.5 w-3.5" />{t("employee.terminate")}</Button>
      </>}>
        <DetailList items={[
          { label: t("employee.no"), value: <span className="font-mono">{employee.employee_no}</span> },
          { label: t("branch"), value: branchName },
          { label: t("department"), value: departments.data?.find((d) => d.id === employee.department_id)?.name ?? "—" },
          { label: t("employee.hireDate"), value: formatDate(employee.hire_date) },
          ...(employee.termination_date ? [{ label: t("employee.terminationDate"), value: formatDate(employee.termination_date) }] : []),
          { label: t("phone"), value: employee.phone },
          { label: t("email"), value: employee.email },
          { label: t("employee.residency"), value: t(`residency.${employee.residency}`) },
          { label: t("employee.director"), value: employee.is_director ? t("yes") : t("no") },
        ]} />
      </Card>
      <Card title={t("employee.idsHeading")} description={t("employee.idsHint")}>
        <DetailList items={[
          { label: t("employee.nationalId"), value: employee.national_id_masked ? <span className="font-mono">{employee.national_id_masked}</span> : null },
          { label: t("employee.taxId"), value: employee.tax_id ? <span className="font-mono">{employee.tax_id}</span> : null },
          ...registrations.map(([code, number]) => ({ label: ruleName(code), value: <span className="font-mono">{number}</span> })),
        ]} />
        {employee.exempt_rules.length > 0 && (
          <p className="mt-4 text-sm text-muted">{t("employee.exemptFrom", { rules: employee.exempt_rules.map(ruleName).join(", ") })}</p>
        )}
      </Card>
      <EmployeeDrawer open={editing} onClose={() => setEditing(false)} employee={employee} />
      <TerminateModal open={leaving} onClose={() => setLeaving(false)} employee={employee} />
    </div>
  );
}

function TerminateModal({ open, onClose, employee }: { open: boolean; onClose: () => void; employee: Employee }) {
  const { t } = useTranslation("people");
  const qc = useQueryClient();
  const [date, setDate] = useState(today());
  const [reason, setReason] = useState("");
  const end = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/people/employees/{employee_id}/terminate", { params: { path: { employee_id: employee.id } }, body: { termination_date: date, reason: reason.trim() || null } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["people"] }); toast(t("employee.terminated", { name: employee.full_name }), "ok"); onClose(); },
  });
  return (
    <Modal open={open} onClose={onClose} title={t("employee.terminate")} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button variant="danger" loading={end.isPending} disabled={!date} onClick={() => end.mutate()}>{t("employee.terminate")}</Button></>}>
      <p className="mb-3 text-sm text-muted">{t("employee.terminateAsk", { name: employee.full_name })}</p>
      <div className="space-y-3">
        <Field label={t("employee.lastDay")} required><Input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
        <Field label={t("employee.terminateReason")}><Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} /></Field>
      </div>
    </Modal>
  );
}
