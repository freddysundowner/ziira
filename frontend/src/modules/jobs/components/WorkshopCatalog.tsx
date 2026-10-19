import { Pencil, Plus } from "lucide-react";
import { useState } from "react";

import { api, Badge, Button, Card, DataTable, Field, FormGrid, Input, Modal, NumberInput, Select, Switch, unwrap, useTranslation } from "@/sdk";

import { useCatalogAction, useLabourTasks, usePartCategories, useWorkTypes } from "../hooks";
import type { LabourTask, PartCategory, WorkType } from "../types";

/** Work types with their rates, the flat-rate task library (standard times) and the markup by part category. */
export function WorkshopCatalog({ companyId, currency }: { companyId: string; currency: string | undefined }) {
  return (
    <div className="space-y-4">
      <WorkTypes companyId={companyId} currency={currency} />
      <Tasks companyId={companyId} currency={currency} />
      <Categories companyId={companyId} />
    </div>
  );
}

function WorkTypes({ companyId, currency }: { companyId: string; currency: string | undefined }) {
  const { t } = useTranslation("jobs");
  const rows = useWorkTypes(companyId);
  const [editing, setEditing] = useState<WorkType | "new" | null>(null);
  return (
    <Card title={t("garage.catalog.workTypes")} description={t("garage.catalog.workTypesHint")} flush
      actions={<Button size="sm" onClick={() => setEditing("new")}><Plus className="h-4 w-4" />{t("garage.catalog.add")}</Button>}>
      <DataTable rows={rows.data} loading={rows.isLoading} error={rows.error?.message} rowKey={(r) => r.id} empty={{ title: t("garage.catalog.noWorkTypes") }}
        columns={[
          { header: t("garage.catalog.name"), cell: (r) => <span className={r.is_active ? "font-medium" : "text-muted line-through"}>{r.name}</span> },
          { header: t("garage.catalog.rate"), align: "right", cell: (r) => (r.hourly_rate ? <span className="tnum">{Number(r.hourly_rate)}</span> : <span className="text-muted">{t("garage.catalog.companyRate")}</span>) },
          { header: "", align: "right", cell: (r) => <Button size="sm" variant="ghost" onClick={() => setEditing(r)}><Pencil className="h-4 w-4" />{t("actions.edit")}</Button> },
        ]} />
      {editing && <WorkTypeModal companyId={companyId} row={editing === "new" ? null : editing} currency={currency} onClose={() => setEditing(null)} />}
    </Card>
  );
}

function WorkTypeModal({ companyId, row, currency, onClose }: { companyId: string; row: WorkType | null; currency: string | undefined; onClose: () => void }) {
  const { t } = useTranslation("jobs");
  const [name, setName] = useState(row?.name ?? "");
  const [rate, setRate] = useState(row?.hourly_rate ?? "");
  const [active, setActive] = useState(row?.is_active ?? true);
  const save = useCatalogAction(() => row
    ? unwrap(api.PATCH("/api/v1/jobs/work-types/{row_id}", { params: { path: { row_id: row.id } }, body: { name: name.trim(), hourly_rate: rate === "" ? null : rate, is_active: active } }))
    : unwrap(api.POST("/api/v1/jobs/work-types", { body: { company_id: companyId, name: name.trim(), code: null, hourly_rate: rate === "" ? null : rate, position: 0 } })), { done: t("garage.catalog.saved"), onDone: onClose });
  return (
    <Modal open onClose={onClose} title={row ? row.name : t("garage.catalog.addWorkType")} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button loading={save.isPending} disabled={!name.trim()} onClick={() => save.mutate(undefined)}>{t("common.save")}</Button></>}>
      <div className="space-y-4">
        <Field label={t("garage.catalog.name")} required><Input maxLength={60} value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label={t("garage.catalog.rate")} hint={t("garage.catalog.rateHint", { currency: currency ?? "" })}><NumberInput value={rate} onChange={setRate} placeholder={t("garage.catalog.companyRate")} /></Field>
        {row && <div className="flex items-center gap-2 text-sm"><Switch checked={active} onChange={setActive} label={t("garage.catalog.inUse")} /><span>{t("garage.catalog.inUse")}</span></div>}
      </div>
    </Modal>
  );
}

function Tasks({ companyId, currency }: { companyId: string; currency: string | undefined }) {
  const { t } = useTranslation("jobs");
  const rows = useLabourTasks(companyId);
  const [editing, setEditing] = useState<LabourTask | "new" | null>(null);
  const examples = (rows.data ?? []).filter((r) => r.is_example && r.is_active).length;
  return (
    <Card title={t("garage.catalog.tasks")} description={t("garage.catalog.tasksHint")} flush
      actions={<Button size="sm" onClick={() => setEditing("new")}><Plus className="h-4 w-4" />{t("garage.catalog.add")}</Button>}>
      {examples > 0 && <p className="border-b border-line bg-warn-soft px-4 py-2 text-sm text-warn">{t("garage.catalog.examples", { n: examples })}</p>}
      <DataTable rows={rows.data} loading={rows.isLoading} error={rows.error?.message} rowKey={(r) => r.id} empty={{ title: t("garage.catalog.noTasks"), hint: t("garage.catalog.noTasksHint") }}
        columns={[
          { header: t("garage.catalog.name"), cell: (r) => <span className={r.is_active ? "font-medium" : "text-muted line-through"}>{r.name}{r.is_example && <Badge tone="warn" className="ml-2">{t("garage.catalog.example")}</Badge>}</span> },
          { header: t("garage.catalog.workType"), hideBelow: "sm", cell: (r) => r.work_type_code ?? "—" },
          { header: t("garage.catalog.hours"), align: "right", cell: (r) => <span className="tnum">{Number(r.standard_hours)}</span> },
          { header: t("garage.catalog.fixedPrice"), align: "right", hideBelow: "md", cell: (r) => (r.flat_price ? <span className="tnum">{Number(r.flat_price)}</span> : "—") },
          { header: "", align: "right", cell: (r) => <Button size="sm" variant="ghost" onClick={() => setEditing(r)}><Pencil className="h-4 w-4" />{t("actions.edit")}</Button> },
        ]} />
      {editing && <TaskModal companyId={companyId} row={editing === "new" ? null : editing} currency={currency} onClose={() => setEditing(null)} />}
    </Card>
  );
}

function TaskModal({ companyId, row, currency, onClose }: { companyId: string; row: LabourTask | null; currency: string | undefined; onClose: () => void }) {
  const { t } = useTranslation("jobs");
  const types = useWorkTypes(companyId, true);
  const [name, setName] = useState(row?.name ?? "");
  const [hours, setHours] = useState(row ? String(Number(row.standard_hours)) : "");
  const [workType, setWorkType] = useState(row?.work_type_code ?? "");
  const [flat, setFlat] = useState(row?.flat_price ?? "");
  const [active, setActive] = useState(row?.is_active ?? true);
  const save = useCatalogAction(() => row
    ? unwrap(api.PATCH("/api/v1/jobs/labour-tasks/{row_id}", { params: { path: { row_id: row.id } }, body: { name: name.trim(), standard_hours: hours, work_type_code: workType || null, flat_price: flat === "" ? null : flat, is_active: active } }))
    : unwrap(api.POST("/api/v1/jobs/labour-tasks", { body: { company_id: companyId, name: name.trim(), code: null, standard_hours: hours, work_type_code: workType || null, flat_price: flat === "" ? null : flat, asset_kind: null } })),
  { done: t("garage.catalog.saved"), onDone: onClose });
  return (
    <Modal open onClose={onClose} title={row ? row.name : t("garage.catalog.addTask")} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button loading={save.isPending} disabled={!name.trim() || !(Number(hours) > 0)} onClick={() => save.mutate(undefined)}>{t("common.save")}</Button></>}>
      <div className="space-y-4">
        <Field label={t("garage.catalog.name")} required><Input maxLength={160} value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <FormGrid>
          <Field label={t("garage.catalog.hours")} required hint={t("garage.catalog.hoursHint")}><NumberInput value={hours} onChange={setHours} /></Field>
          <Field label={t("garage.catalog.workType")}>
            <Select value={workType} onChange={(e) => setWorkType(e.target.value)}>
              <option value="">—</option>
              {(types.data ?? []).map((w) => <option key={w.id} value={w.code}>{w.name}</option>)}
            </Select>
          </Field>
        </FormGrid>
        <Field label={t("garage.catalog.fixedPrice")} hint={t("garage.catalog.fixedPriceHint", { currency: currency ?? "" })}><NumberInput value={flat} onChange={setFlat} /></Field>
        {row && <div className="flex items-center gap-2 text-sm"><Switch checked={active} onChange={setActive} label={t("garage.catalog.inUse")} /><span>{t("garage.catalog.inUse")}</span></div>}
      </div>
    </Modal>
  );
}

function Categories({ companyId }: { companyId: string }) {
  const { t } = useTranslation("jobs");
  const rows = usePartCategories(companyId);
  const [editing, setEditing] = useState<PartCategory | "new" | null>(null);
  return (
    <Card title={t("garage.catalog.categories")} description={t("garage.catalog.categoriesHint")} flush
      actions={<Button size="sm" onClick={() => setEditing("new")}><Plus className="h-4 w-4" />{t("garage.catalog.add")}</Button>}>
      <DataTable rows={rows.data} loading={rows.isLoading} error={rows.error?.message} rowKey={(r) => r.id} empty={{ title: t("garage.catalog.noCategories") }}
        columns={[
          { header: t("garage.catalog.name"), cell: (r) => <span className={r.is_active ? "font-medium" : "text-muted line-through"}>{r.name}</span> },
          { header: t("garage.parts.class"), hideBelow: "sm", cell: (r) => (r.default_class ? t(`garage.parts.classes.${r.default_class}`) : "—") },
          { header: t("garage.catalog.markup"), align: "right", cell: (r) => <span className="tnum">{Number(r.markup_percent)}%</span> },
          { header: "", align: "right", cell: (r) => <Button size="sm" variant="ghost" onClick={() => setEditing(r)}><Pencil className="h-4 w-4" />{t("actions.edit")}</Button> },
        ]} />
      {editing && <CategoryModal companyId={companyId} row={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </Card>
  );
}

function CategoryModal({ companyId, row, onClose }: { companyId: string; row: PartCategory | null; onClose: () => void }) {
  const { t } = useTranslation("jobs");
  const [name, setName] = useState(row?.name ?? "");
  const [markup, setMarkup] = useState(row ? String(Number(row.markup_percent)) : "0");
  const [cls, setCls] = useState(row?.default_class ?? "");
  const [active, setActive] = useState(row?.is_active ?? true);
  const klass = (cls || null) as "genuine" | "aftermarket" | "used" | null;
  const save = useCatalogAction(() => row
    ? unwrap(api.PATCH("/api/v1/jobs/part-categories/{row_id}", { params: { path: { row_id: row.id } }, body: { name: name.trim(), markup_percent: markup || "0", default_class: klass, is_active: active } }))
    : unwrap(api.POST("/api/v1/jobs/part-categories", { body: { company_id: companyId, name: name.trim(), code: null, markup_percent: markup || "0", default_class: klass, position: 0 } })),
  { done: t("garage.catalog.saved"), onDone: onClose });
  return (
    <Modal open onClose={onClose} title={row ? row.name : t("garage.catalog.addCategory")} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button loading={save.isPending} disabled={!name.trim()} onClick={() => save.mutate(undefined)}>{t("common.save")}</Button></>}>
      <div className="space-y-4">
        <Field label={t("garage.catalog.name")} required><Input maxLength={60} value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <FormGrid>
          <Field label={t("garage.catalog.markup")} hint={t("garage.catalog.markupHint")}><NumberInput value={markup} onChange={setMarkup} /></Field>
          <Field label={t("garage.parts.class")}>
            <Select value={cls} onChange={(e) => setCls(e.target.value)}>
              <option value="">{t("garage.parts.noClass")}</option>
              {(["genuine", "aftermarket", "used"] as const).map((c) => <option key={c} value={c}>{t(`garage.parts.classes.${c}`)}</option>)}
            </Select>
          </Field>
        </FormGrid>
        {row && <div className="flex items-center gap-2 text-sm"><Switch checked={active} onChange={setActive} label={t("garage.catalog.inUse")} /><span>{t("garage.catalog.inUse")}</span></div>}
      </div>
    </Modal>
  );
}
