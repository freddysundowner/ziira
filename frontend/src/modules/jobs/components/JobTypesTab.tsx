import { Pencil, Plus, X } from "lucide-react";
import { useState } from "react";

import { api, Badge, Button, Card, DataTable, Field, FormGrid, IconButton, Input, Modal, NumberInput, Select, Switch, unwrap, useTranslation } from "@/sdk";

import { useCatalogAction, useJobTypes, usePhotoCategories, useTemplates } from "../hooks";
import type { JobType } from "../types";

const ROLES = ["quoted", "approved", "ready", "collected", "closed"] as const;
type Rule = { category: string; min: string; before: (typeof ROLES)[number] };

/** The kinds of job a business does (a service, a body repair, an alteration): their checklist, their warranty and the photos they need. */
export function JobTypesTab({ companyId }: { companyId: string }) {
  return (
    <div className="space-y-4">
      <JobTypes companyId={companyId} />
      <PhotoKinds companyId={companyId} />
    </div>
  );
}

function JobTypes({ companyId }: { companyId: string }) {
  const { t } = useTranslation("jobs");
  const rows = useJobTypes(companyId);
  const [editing, setEditing] = useState<JobType | "new" | null>(null);
  return (
    <Card title={t("garage.types.title")} description={t("garage.types.hint")} flush actions={<Button size="sm" onClick={() => setEditing("new")}><Plus className="h-4 w-4" />{t("garage.catalog.add")}</Button>}>
      <DataTable rows={rows.data} loading={rows.isLoading} error={rows.error?.message} rowKey={(r) => r.id} empty={{ title: t("garage.types.empty"), hint: t("garage.types.emptyHint") }}
        columns={[
          { header: t("garage.catalog.name"), cell: (r) => <span className={r.is_active ? "font-medium" : "text-muted line-through"}>{r.name}</span> },
          { header: t("garage.types.warranty"), hideBelow: "sm", cell: (r) => (r.default_warranty_days != null ? t("summary.days", { n: r.default_warranty_days }) : "—") },
          { header: t("garage.types.photos"), hideBelow: "md", cell: (r) => (r.required_photos.length > 0 ? <Badge tone="info">{t("garage.types.photoRules", { n: r.required_photos.length })}</Badge> : "—") },
          { header: "", align: "right", cell: (r) => <Button size="sm" variant="ghost" onClick={() => setEditing(r)}><Pencil className="h-4 w-4" />{t("actions.edit")}</Button> },
        ]} />
      {editing && <TypeModal companyId={companyId} row={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </Card>
  );
}

function TypeModal({ companyId, row, onClose }: { companyId: string; row: JobType | null; onClose: () => void }) {
  const { t } = useTranslation("jobs");
  const templates = useTemplates(companyId, true);
  const kinds = usePhotoCategories(companyId, true);
  const [name, setName] = useState(row?.name ?? "");
  const [template, setTemplate] = useState(row?.checklist_template_id ?? "");
  const [warranty, setWarranty] = useState(row?.default_warranty_days != null ? String(row.default_warranty_days) : "");
  const [active, setActive] = useState(row?.is_active ?? true);
  const [rules, setRules] = useState<Rule[]>((row?.required_photos ?? []).map((r) => ({ category: r.category, min: String(r.min), before: r.before })));
  const body = () => rules.filter((r) => r.category && Number(r.min) > 0).map((r) => ({ category: r.category, min: Number(r.min), before: r.before }));
  const save = useCatalogAction(() => row
    ? unwrap(api.PATCH("/api/v1/jobs/job-types/{row_id}", { params: { path: { row_id: row.id } }, body: { name: name.trim(), checklist_template_id: template || null, default_warranty_days: warranty === "" ? null : Number(warranty), required_photos: body(), is_active: active } }))
    : unwrap(api.POST("/api/v1/jobs/job-types", { body: { company_id: companyId, name: name.trim(), code: null, checklist_template_id: template || null, default_warranty_days: warranty === "" ? null : Number(warranty), required_photos: body(), position: 0 } })),
  { done: t("garage.catalog.saved"), onDone: onClose });
  const setRule = (i: number, patch: Partial<Rule>) => setRules((all) => all.map((r, at) => (at === i ? { ...r, ...patch } : r)));
  return (
    <Modal open onClose={onClose} title={row ? row.name : t("garage.types.add")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button loading={save.isPending} disabled={!name.trim()} onClick={() => save.mutate(undefined)}>{t("common.save")}</Button></>}>
      <div className="space-y-4">
        <Field label={t("garage.catalog.name")} required><Input maxLength={60} value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <FormGrid>
          <Field label={t("garage.types.checklist")}>
            <Select value={template} onChange={(e) => setTemplate(e.target.value)}><option value="">—</option>{(templates.data ?? []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</Select>
          </Field>
          <Field label={t("garage.types.warranty")} hint={t("garage.types.warrantyHint")}><NumberInput value={warranty} onChange={(v) => setWarranty(v.replace(/\./g, ""))} /></Field>
        </FormGrid>
        <fieldset className="space-y-3">
          <legend className="text-sm font-medium">{t("garage.types.photos")}</legend>
          <p className="text-xs text-muted">{t("garage.types.photosHint")}</p>
          {rules.map((r, i) => (
            <div key={i} className="grid grid-cols-[1fr_4.5rem_1fr_auto] items-end gap-2">
              <Select aria-label={t("garage.photos.kind")} value={r.category} onChange={(e) => setRule(i, { category: e.target.value })}>
                <option value="">—</option>{(kinds.data ?? []).map((k) => <option key={k.id} value={k.code}>{k.name}</option>)}
              </Select>
              <NumberInput aria-label={t("garage.types.howMany")} value={r.min} onChange={(v) => setRule(i, { min: v.replace(/\./g, "") })} />
              <Select aria-label={t("garage.types.before")} value={r.before} onChange={(e) => setRule(i, { before: e.target.value as Rule["before"] })}>
                {ROLES.map((x) => <option key={x} value={x}>{t("garage.photos.before", { stage: t(`garage.photos.stage.${x}`) })}</option>)}
              </Select>
              <IconButton label={t("common.remove")} onClick={() => setRules((all) => all.filter((_, at) => at !== i))}><X className="h-4 w-4" /></IconButton>
            </div>
          ))}
          <Button size="sm" variant="secondary" onClick={() => setRules((all) => [...all, { category: kinds.data?.[0]?.code ?? "", min: "1", before: "quoted" }])}><Plus className="h-4 w-4" />{t("garage.types.addRule")}</Button>
        </fieldset>
        {row && <div className="flex items-center gap-2 text-sm"><Switch checked={active} onChange={setActive} label={t("garage.catalog.inUse")} /><span>{t("garage.catalog.inUse")}</span></div>}
      </div>
    </Modal>
  );
}

function PhotoKinds({ companyId }: { companyId: string }) {
  const { t } = useTranslation("jobs");
  const rows = usePhotoCategories(companyId);
  const [name, setName] = useState("");
  const add = useCatalogAction(() => unwrap(api.POST("/api/v1/jobs/photo-categories", { body: { company_id: companyId, name: name.trim(), code: null, position: 0 } })), { done: t("garage.catalog.saved"), onDone: () => setName("") });
  const toggle = useCatalogAction((v: { id: string; active: boolean }) => unwrap(api.PATCH("/api/v1/jobs/photo-categories/{row_id}", { params: { path: { row_id: v.id } }, body: { is_active: v.active } })));
  return (
    <Card title={t("garage.photos.kinds")} description={t("garage.photos.kindsHint")}>
      <ul className="mb-3 flex flex-wrap gap-2">
        {(rows.data ?? []).map((k) => (
          <li key={k.id}>
            <button type="button" aria-pressed={k.is_active} onClick={() => toggle.mutate({ id: k.id, active: !k.is_active })}
              className={`rounded-full border px-3 py-1 text-sm ${k.is_active ? "border-brand/40 bg-brand-soft" : "border-line text-muted line-through"}`}>{k.name}</button>
          </li>
        ))}
        {(rows.data ?? []).length === 0 && <li className="text-sm text-muted">{t("garage.photos.kindsDefault")}</li>}
      </ul>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (name.trim()) add.mutate(undefined); }}>
        <Input aria-label={t("garage.photos.newKind")} placeholder={t("garage.photos.newKind")} maxLength={60} value={name} onChange={(e) => setName(e.target.value)} />
        <Button type="submit" variant="secondary" loading={add.isPending} disabled={!name.trim()}><Plus className="h-4 w-4" />{t("common.add")}</Button>
      </form>
    </Card>
  );
}
