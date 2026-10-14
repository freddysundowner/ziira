import { Building, Plus } from "lucide-react";
import { useState } from "react";

import {
  api, Badge, Button, DataTable, formatDate, Input, Pager, PageHeader, Select, StatusBadge, unwrap, useCan, useDebounced, usePagedList, useTranslation,
} from "@/sdk";

import { CompanySelect } from "../components/CompanySelect";
import { DepartmentsModal } from "../components/DepartmentsModal";
import { EmployeeDrawer } from "../components/EmployeeDrawer";
import { useDepartments, useScope } from "../lib/lookups";

export default function EmployeesPage() {
  const { t } = useTranslation("people");
  const canManage = useCan("employees.manage");
  const scope = useScope();
  const [creating, setCreating] = useState(false);
  const [departmentsOpen, setDepartmentsOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [branch, setBranch] = useState("");
  const [department, setDepartment] = useState("");
  const q = useDebounced(search.trim());
  const departments = useDepartments(scope.companyId);
  const branchName = (id: string | null) => scope.branches.find((b) => b.id === id)?.name ?? "—";
  const departmentName = (id: string | null) => departments.data?.find((d) => d.id === id)?.name ?? "—";

  const list = usePagedList(["people", "employees", scope.companyId, q, status, branch, department], (limit, offset) =>
    unwrap(api.GET("/api/v1/people/employees", { params: { query: {
      company_id: scope.companyId || undefined, search: q || undefined, status: (status || undefined) as "active" | undefined,
      branch_id: branch || undefined, department_id: department || undefined, limit, offset } } })));
  const filtered = !!(q || status || branch || department);

  return (
    <>
      <PageHeader title={t("employees.title")} description={t("employees.hint")} actions={<>
        <Button variant="secondary" onClick={() => setDepartmentsOpen(true)}><Building className="h-4 w-4" />{t("dept.title")}</Button>
        {canManage && <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" />{t("employee.new")}</Button>}
      </>} />
      <DataTable
        rows={list.rows} loading={list.query.isLoading || scope.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()}
        rowKey={(e) => e.id} rowHref={(e) => `/employees/${e.id}`}
        toolbar={<>
          <Input className="max-w-xs" aria-label={t("employees.search")} placeholder={t("employees.search")} value={search} onChange={(e) => setSearch(e.target.value)} />
          <CompanySelect companies={scope.companies} value={scope.companyId} onChange={(id) => { scope.setCompanyId(id); setBranch(""); setDepartment(""); }} />
          <Select aria-label={t("status")} className="w-auto" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("employees.anyStatus")}</option>
            {(["active", "on_leave", "terminated"] as const).map((s) => <option key={s} value={s}>{t(`state.${s}`)}</option>)}
          </Select>
          {scope.branches.length > 1 && (
            <Select aria-label={t("branch")} className="w-auto" value={branch} onChange={(e) => setBranch(e.target.value)}>
              <option value="">{t("allBranches")}</option>{scope.branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </Select>
          )}
          {(departments.data ?? []).length > 0 && (
            <Select aria-label={t("department")} className="w-auto" value={department} onChange={(e) => setDepartment(e.target.value)}>
              <option value="">{t("employees.anyDepartment")}</option>{(departments.data ?? []).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </Select>
          )}
        </>}
        empty={{ title: filtered ? t("employees.noMatch") : t("employees.empty"), hint: filtered ? undefined : t("employees.emptyHint"), action: canManage && !filtered ? <Button onClick={() => setCreating(true)}>{t("employee.new")}</Button> : undefined }}
        columns={[
          { header: t("employee.no"), hideBelow: "sm", sortValue: (e) => e.employee_no, cell: (e) => <span className="font-mono text-xs">{e.employee_no}</span> },
          { header: t("employee.fullName"), sortValue: (e) => e.full_name, cell: (e) => <span className="font-medium">{e.full_name}{e.is_director && <Badge className="ml-2">{t("employee.directorShort")}</Badge>}</span> },
          { header: t("branch"), hideBelow: "md", cell: (e) => branchName(e.branch_id) },
          { header: t("department"), hideBelow: "lg", cell: (e) => departmentName(e.department_id) },
          { header: t("employee.hireDate"), hideBelow: "lg", sortValue: (e) => e.hire_date, cell: (e) => formatDate(e.hire_date) },
          { header: t("status"), cell: (e) => <StatusBadge status={e.status} /> },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
      <EmployeeDrawer open={creating} onClose={() => setCreating(false)} />
      <DepartmentsModal open={departmentsOpen} onClose={() => setDepartmentsOpen(false)} companyId={scope.companyId} />
    </>
  );
}
