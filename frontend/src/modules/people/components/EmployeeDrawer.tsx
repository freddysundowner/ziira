import { Plus, X } from "lucide-react";
import { type FormEvent, useState } from "react";

import {
  api, Button, Checkbox, ErrorText, Field, FormGrid, IconButton, Input, orNull, Select, toast, unwrap, useFormState, useMutation, useQuery, useQueryClient,
  useTranslation, Drawer, ApiError, today,
} from "@/sdk";

import { useDepartments, useRules, useScope } from "../lib/lookups";
import type { Employee } from "../lib/types";

/** Add an employee, or change one. The body mounts only while open, so the form starts fresh each time. */
export function EmployeeDrawer({ open, onClose, employee }: { open: boolean; onClose: () => void; employee?: Employee }) {
  return open ? <Body onClose={onClose} employee={employee} /> : null;
}

function Body({ onClose, employee }: { onClose: () => void; employee?: Employee }) {
  const { t } = useTranslation("people");
  const qc = useQueryClient();
  const scope = useScope();
  const editing = !!employee;
  const companyId = employee?.company_id ?? scope.companyId;
  const company = scope.companies.find((c) => c.id === companyId);
  const f = useFormState({
    company_id: companyId, full_name: employee?.full_name ?? "", hire_date: employee?.hire_date ?? today(), branch_id: employee?.branch_id ?? "",
    department_id: employee?.department_id ?? "", employee_no: employee?.employee_no ?? "", national_id: "", tax_id: employee?.tax_id ?? "",
    phone: employee?.phone ?? "", email: employee?.email ?? "", residency: employee?.residency ?? "resident", user_id: employee?.user_id ?? "",
  });
  const [director, setDirector] = useState(employee?.is_director ?? false);
  const [registrations, setRegistrations] = useState<[string, string][]>(Object.entries(employee?.registrations ?? {}));
  const [exempt, setExempt] = useState<string[]>(employee?.exempt_rules ?? []);
  const cid = f.values.company_id;
  const departments = useDepartments(cid);
  const rules = useRules(cid);
  const users = useQuery({ queryKey: ["users"], queryFn: () => unwrap(api.GET("/api/v1/users")), retry: false });
  const knownRules = [...new Map((rules.data ?? []).map((r) => [r.code, String((r.definition as { name?: string }).name ?? r.code)])).entries()];

  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => {
      const v = f.values;
      const regs = Object.fromEntries(registrations.filter(([c, n]) => c.trim() && n.trim()).map(([c, n]) => [c.trim().toUpperCase(), n.trim()]));
      const shared = {
        full_name: v.full_name.trim(), branch_id: v.branch_id || null, department_id: v.department_id || null, user_id: v.user_id || null,
        tax_id: orNull(v.tax_id), phone: orNull(v.phone), email: orNull(v.email), residency: v.residency as "resident", is_director: director,
        registrations: regs, exempt_rules: exempt,
      };
      if (employee) {
        return unwrap(api.PATCH("/api/v1/people/employees/{employee_id}", {
          params: { path: { employee_id: employee.id } }, body: { ...shared, ...(v.national_id.trim() ? { national_id: v.national_id.trim() } : {}) },
        }));
      }
      return unwrap(api.POST("/api/v1/people/employees", { body: { ...shared, company_id: v.company_id, hire_date: v.hire_date, employee_no: orNull(v.employee_no), national_id: orNull(v.national_id) } }));
    },
    onSuccess: (e) => {
      void qc.invalidateQueries({ queryKey: ["people"] });
      toast(t(editing ? "employee.saved" : "employee.created", { name: e.full_name }), "ok");
      onClose();
    },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  const showForm = save.error instanceof ApiError && Object.keys(save.error.fields).length === 0 ? save.error.message : null;

  return (
    <Drawer open onClose={onClose} title={editing ? t("employee.edit") : t("employee.new")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="employee-form" loading={save.isPending}>{t("save")}</Button></>}>
      <form id="employee-form" onSubmit={submit} className="space-y-4">
        {!editing && scope.companies.length > 1 && (
          <Field label={t("company")}><Select {...f.bind("company_id")}>{scope.companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select></Field>
        )}
        <Field label={t("employee.fullName")} required error={f.error("full_name")}><Input {...f.bind("full_name")} required autoFocus /></Field>
        <FormGrid>
          <Field label={t("employee.hireDate")} required error={f.error("hire_date")}><Input type="date" {...f.bind("hire_date")} required disabled={editing} /></Field>
          <Field label={t("employee.no")} hint={editing ? undefined : t("employee.noHint")} error={f.error("employee_no")}><Input {...f.bind("employee_no")} disabled={editing} /></Field>
          <Field label={t("branch")} error={f.error("branch_id")}>
            <Select {...f.bind("branch_id")}><option value="">{t("none")}</option>{(company?.branches ?? []).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</Select>
          </Field>
          <Field label={t("department")} error={f.error("department_id")}>
            <Select {...f.bind("department_id")}><option value="">{t("none")}</option>{(departments.data ?? []).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</Select>
          </Field>
          <Field label={t("phone")} error={f.error("phone")}><Input type="tel" {...f.bind("phone")} /></Field>
          <Field label={t("email")} error={f.error("email")}><Input type="email" {...f.bind("email")} /></Field>
        </FormGrid>
        <h3 className="pt-2 text-sm font-semibold">{t("employee.idsHeading")}</h3>
        <FormGrid>
          <Field label={t("employee.nationalId")} error={f.error("national_id")} hint={editing ? t("employee.nationalIdKeep", { masked: employee?.national_id_masked ?? "—" }) : undefined}>
            <Input {...f.bind("national_id")} autoComplete="off" />
          </Field>
          <Field label={t("employee.taxId")} error={f.error("tax_id")}><Input {...f.bind("tax_id")} /></Field>
          <Field label={t("employee.residency")} hint={t("employee.residencyHint")}>
            <Select {...f.bind("residency")}><option value="resident">{t("residency.resident")}</option><option value="non_resident">{t("residency.non_resident")}</option></Select>
          </Field>
          {users.data && (
            <Field label={t("employee.user")} hint={t("employee.userHint")}>
              <Select {...f.bind("user_id")}><option value="">{t("none")}</option>{users.data.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}</Select>
            </Field>
          )}
        </FormGrid>
        <Checkbox label={t("employee.director")} checked={director} onChange={(e) => setDirector(e.target.checked)} />

        <section className="space-y-2 rounded-xl bg-sunken p-4">
          <h3 className="text-sm font-semibold">{t("employee.registrations")}</h3>
          <p className="text-xs text-muted">{t("employee.registrationsHint")}</p>
          <datalist id="rule-codes">{knownRules.map(([code, name]) => <option key={code} value={code}>{name}</option>)}</datalist>
          {registrations.map(([code, number], i) => (
            <div key={i} className="flex items-center gap-2">
              <Input aria-label={t("employee.ruleCode")} list="rule-codes" placeholder={t("employee.ruleCode")} value={code} onChange={(e) => setRegistrations((r) => r.map((x, j) => (j === i ? [e.target.value, x[1]] : x)))} />
              <Input aria-label={t("employee.registrationNo")} placeholder={t("employee.registrationNo")} value={number} onChange={(e) => setRegistrations((r) => r.map((x, j) => (j === i ? [x[0], e.target.value] : x)))} />
              <IconButton label={t("remove")} onClick={() => setRegistrations((r) => r.filter((_, j) => j !== i))}><X className="h-4 w-4" /></IconButton>
            </div>
          ))}
          <Button variant="secondary" size="sm" onClick={() => setRegistrations((r) => [...r, ["", ""]])}><Plus className="h-3.5 w-3.5" />{t("employee.addRegistration")}</Button>
        </section>

        {(knownRules.length > 0 || exempt.length > 0) && (
          <section className="space-y-2">
            <h3 className="text-sm font-semibold">{t("employee.exempt")}</h3>
            <p className="text-xs text-muted">{t("employee.exemptHint")}</p>
            <div className="flex flex-col gap-1.5">
              {[...new Set([...knownRules.map(([c]) => c), ...exempt])].map((code) => (
                <Checkbox key={code} label={<span>{knownRules.find(([c]) => c === code)?.[1] ?? code} <span className="font-mono text-xs text-muted">{code}</span></span>}
                  checked={exempt.includes(code)} onChange={(e) => setExempt((x) => (e.target.checked ? [...x, code] : x.filter((c) => c !== code)))} />
              ))}
            </div>
          </section>
        )}
        <ErrorText>{showForm}</ErrorText>
      </form>
    </Drawer>
  );
}
