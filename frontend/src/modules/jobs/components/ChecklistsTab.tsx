import { Pencil, Plus } from "lucide-react";
import { useState } from "react";

import { api, Badge, Button, Card, Drawer, EmptyState, ErrorState, Field, FormGrid, IconButton, Input, Skeleton, Switch, Textarea, toast, unwrap, useMutation, useQueryClient, useTranslation } from "@/sdk";

import { useTemplates } from "../hooks";
import type { Template } from "../types";

/** The intake checklists a new job can copy ("fuel level noted", "charger present"...). One line per item. */
export function ChecklistsTab({ companyId }: { companyId: string }) {
  const { t } = useTranslation("jobs");
  const templates = useTemplates(companyId);
  const [editing, setEditing] = useState<Template | "new" | null>(null);
  if (templates.error) return <ErrorState title={t("checklists.loadFailed")} message={templates.error.message} onRetry={() => void templates.refetch()} />;
  if (!templates.data) return <Skeleton className="h-48" />;
  return (
    <Card title={t("checklists.title")} actions={<Button size="sm" onClick={() => setEditing("new")}><Plus className="h-4 w-4" />{t("checklists.add")}</Button>}>
      {templates.data.length === 0 ? (
        <EmptyState title={t("checklists.empty")} hint={t("checklists.emptyHint")} action={<Button onClick={() => setEditing("new")}>{t("checklists.add")}</Button>} />
      ) : (
        <ul className="divide-y divide-line">
          {templates.data.map((tpl) => (
            <li key={tpl.id} className="flex items-center gap-3 py-3">
              <div className="min-w-0 flex-1">
                <p className="flex flex-wrap items-center gap-2 font-medium">{tpl.name}{tpl.asset_kind && <Badge tone="neutral">{tpl.asset_kind}</Badge>}{!tpl.is_active && <Badge tone="neutral">{t("stages.off")}</Badge>}</p>
                <p className="truncate text-xs text-muted">{t("checklists.lines", { n: tpl.items.length })}: {tpl.items.join(", ")}</p>
              </div>
              <IconButton label={t("checklists.edit", { name: tpl.name })} onClick={() => setEditing(tpl)}><Pencil className="h-4 w-4" /></IconButton>
            </li>
          ))}
        </ul>
      )}
      {editing && <TemplateDrawer companyId={companyId} template={editing === "new" ? undefined : editing} onClose={() => setEditing(null)} />}
    </Card>
  );
}

function TemplateDrawer({ companyId, template, onClose }: { companyId: string; template?: Template; onClose: () => void }) {
  const { t } = useTranslation("jobs");
  const qc = useQueryClient();
  const [name, setName] = useState(template?.name ?? "");
  const [kind, setKind] = useState(template?.asset_kind ?? "");
  const [lines, setLines] = useState((template?.items ?? []).join("\n"));
  const [active, setActive] = useState(template?.is_active ?? true);
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => {
      const items = lines.split("\n").map((l) => l.trim()).filter(Boolean);
      return template
        ? unwrap(api.PATCH("/api/v1/jobs/checklist-templates/{template_id}", { params: { path: { template_id: template.id } }, body: { name: name.trim(), items, asset_kind: kind.trim() || null, is_active: active } }))
        : unwrap(api.POST("/api/v1/jobs/checklist-templates", { body: { company_id: companyId, name: name.trim(), items, asset_kind: kind.trim() || null } }));
    },
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["jobs"] }); toast(t("checklists.saved"), "ok"); onClose(); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  return (
    <Drawer open onClose={onClose} title={t(template ? "checklists.editTitle" : "checklists.newTitle")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button loading={save.isPending} disabled={!name.trim()} onClick={() => save.mutate()}>{t("common.save")}</Button></>}>
      <div className="space-y-4">
        <FormGrid>
          <Field label={t("checklists.name")} required><Input maxLength={80} value={name} onChange={(e) => setName(e.target.value)} autoFocus /></Field>
          <Field label={t("checklists.kind")} hint={t("checklists.kindHint")}><Input maxLength={40} value={kind} onChange={(e) => setKind(e.target.value)} /></Field>
        </FormGrid>
        <Field label={t("checklists.linesLabel")} hint={t("checklists.linesHint")}><Textarea rows={8} value={lines} onChange={(e) => setLines(e.target.value)} /></Field>
        {template && <div className="flex items-center gap-2 text-sm"><Switch checked={active} onChange={setActive} label={t("checklists.active")} /><span>{t("checklists.active")}</span></div>}
      </div>
    </Drawer>
  );
}
