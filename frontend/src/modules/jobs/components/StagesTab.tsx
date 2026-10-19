import { Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { api, Alert, Badge, Button, Card, Checkbox, ConfirmDialog, Drawer, ErrorState, Field, FormGrid, IconButton, Input, Select, Skeleton, Switch, toast, unwrap, useMutation, useQueryClient, useTranslation } from "@/sdk";

import { useWorkflow } from "../hooks";
import { KINDS, ROLES, type Stage } from "../types";
import { stageTone } from "../lib";

/** The stages a job moves through and, for each, where it may go next. The business's own words and order. */
export function StagesTab({ companyId }: { companyId: string }) {
  const { t } = useTranslation("jobs");
  const qc = useQueryClient();
  const workflow = useWorkflow(companyId, true);
  const [editing, setEditing] = useState<Stage | "new" | null>(null);
  const [removing, setRemoving] = useState<Stage | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["jobs"] });
  const remove = useMutation({
    mutationFn: (s: Stage) => unwrap(api.DELETE("/api/v1/jobs/statuses/{status_id}", { params: { path: { status_id: s.id } } })),
    onSuccess: () => { void refresh(); toast(t("stages.removed"), "ok"); setRemoving(null); },
    onError: () => setRemoving(null),
  });
  if (workflow.error) return <ErrorState title={t("stages.loadFailed")} message={workflow.error.message} onRetry={() => void workflow.refetch()} />;
  if (!workflow.data) return <Skeleton className="h-64" />;
  const stages = workflow.data;
  const name = (id: string) => stages.find((s) => s.id === id)?.name ?? "";
  return (
    <div className="space-y-4">
      <Alert tone="info">{t("stages.roleHelp")}</Alert>
      <Card title={t("stages.title")} actions={<Button size="sm" onClick={() => setEditing("new")}><Plus className="h-4 w-4" />{t("stages.add")}</Button>}>
        <ul className="divide-y divide-line">
          {stages.map((s) => (
            <li key={s.id} className={`flex flex-wrap items-center gap-x-3 gap-y-1 py-3 ${s.is_active ? "" : "opacity-60"}`}>
              <div className="min-w-0 flex-1">
                <p className="flex flex-wrap items-center gap-2 font-medium">{s.name}
                  <Badge tone={stageTone(s.kind)}>{t(`stages.kind.${s.kind}`)}</Badge>
                  {s.role && <Badge tone="brand">{t(`stages.role.${s.role}`)}</Badge>}
                  {!s.is_active && <Badge tone="neutral">{t("stages.off")}</Badge>}
                </p>
                <p className="text-xs text-muted">{s.moves_to.length ? t("stages.goesTo", { names: s.moves_to.map(name).join(", ") }) : t("stages.goesNowhere")}</p>
              </div>
              <IconButton label={t("stages.edit", { name: s.name })} onClick={() => setEditing(s)}><Pencil className="h-4 w-4" /></IconButton>
              <IconButton label={t("stages.remove", { name: s.name })} onClick={() => setRemoving(s)}><Trash2 className="h-4 w-4" /></IconButton>
            </li>
          ))}
        </ul>
      </Card>
      {editing && <StageDrawer companyId={companyId} stage={editing === "new" ? undefined : editing} stages={stages} onClose={() => setEditing(null)} />}
      <ConfirmDialog open={!!removing} onClose={() => setRemoving(null)} title={t("stages.removeTitle", { name: removing?.name ?? "" })} message={t("stages.removeMessage")}
        confirmLabel={t("common.remove")} danger busy={remove.isPending} onConfirm={() => removing && remove.mutate(removing)} />
    </div>
  );
}

function StageDrawer({ companyId, stage, stages, onClose }: { companyId: string; stage?: Stage; stages: readonly Stage[]; onClose: () => void }) {
  const { t } = useTranslation("jobs");
  const qc = useQueryClient();
  const [code, setCode] = useState("");
  const [name, setName] = useState(stage?.name ?? "");
  const [kind, setKind] = useState<string>(stage?.kind ?? "open");
  const [role, setRole] = useState(stage?.role ?? "");
  const [active, setActive] = useState(stage?.is_active ?? true);
  const [targets, setTargets] = useState<string[]>(stage?.moves_to ?? []);
  const taken = new Map(stages.filter((s) => s.role && s.id !== stage?.id).map((s) => [s.role as string, s.name]));
  const save = useMutation({
    meta: { silent: true },
    mutationFn: async () => {
      const saved = stage
        ? await unwrap(api.PATCH("/api/v1/jobs/statuses/{status_id}", { params: { path: { status_id: stage.id } }, body: { name: name.trim(), kind: kind as "open", role: (role || null) as "initial" | null, is_active: active } }))
        : await unwrap(api.POST("/api/v1/jobs/statuses", { body: { company_id: companyId, code: code.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_"), name: name.trim(), kind: kind as "open", role: (role || null) as "initial" | null } }));
      return unwrap(api.PUT("/api/v1/jobs/statuses/{status_id}/moves", { params: { path: { status_id: saved.id } }, body: { to_status_ids: targets } }));
    },
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["jobs"] }); toast(t("stages.saved"), "ok"); onClose(); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const others = stages.filter((s) => s.id !== stage?.id && s.is_active);
  return (
    <Drawer open onClose={onClose} title={t(stage ? "stages.editTitle" : "stages.newTitle")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button loading={save.isPending} disabled={!name.trim() || (!stage && !code.trim() && !name.trim())} onClick={() => save.mutate()}>{t("common.save")}</Button></>}>
      <div className="space-y-4">
        <Field label={t("stages.name")} required><Input maxLength={60} value={name} onChange={(e) => { setName(e.target.value); if (!stage && !code) setCode(e.target.value); }} autoFocus /></Field>
        {!stage && <Field label={t("stages.code")} hint={t("stages.codeHint")}><Input maxLength={40} value={code} onChange={(e) => setCode(e.target.value)} /></Field>}
        <FormGrid>
          <Field label={t("stages.kindLabel")} hint={t(`stages.kindHint.${kind}`)}>
            <Select value={kind} onChange={(e) => setKind(e.target.value)}>{KINDS.map((k) => <option key={k} value={k}>{t(`stages.kind.${k}`)}</option>)}</Select>
          </Field>
          <Field label={t("stages.roleLabel")} hint={role ? t(`stages.roleHint.${role}`) : t("stages.roleNone")}>
            <Select value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="">{t("stages.roleNone")}</option>
              {ROLES.map((r) => <option key={r} value={r} disabled={taken.has(r)}>{t(`stages.role.${r}`)}{taken.has(r) ? ` (${taken.get(r)})` : ""}</option>)}
            </Select>
          </Field>
        </FormGrid>
        {stage && <div className="flex items-center gap-2 text-sm"><Switch checked={active} onChange={setActive} label={t("stages.active")} /><span>{t("stages.active")}</span></div>}
        <fieldset>
          <legend className="mb-1 text-sm font-medium">{t("stages.movesLegend")}</legend>
          <p className="mb-2 text-xs text-muted">{t("stages.movesHint")}</p>
          <div className="grid gap-1 sm:grid-cols-2">
            {others.map((s) => (
              <Checkbox key={s.id} label={s.name} className="min-h-9 rounded-md px-2 hover:bg-sunken" checked={targets.includes(s.id)}
                onChange={(e) => setTargets((cur) => (e.target.checked ? [...cur, s.id] : cur.filter((x) => x !== s.id)))} />
            ))}
          </div>
        </fieldset>
      </div>
    </Drawer>
  );
}
