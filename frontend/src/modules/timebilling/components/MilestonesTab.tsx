import { Pencil, Plus, Trash2 } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";

import {
  Alert, api, Badge, Button, ConfirmDialog, DataTable, Field, formatDate, FormGrid, IconButton, Input, Modal, money, NumberInput, toast, unwrap, useCan, useFormState, useMutation, useQuery, useTranslation,
} from "@/sdk";

import { useRefresh } from "../hooks";
import type { Milestone, Project } from "../types";

/** The stages of a fixed-fee project: each is billed when it is marked ready. */
export function MilestonesTab({ project, currency }: { project: Project; currency?: string }) {
  const { t } = useTranslation("timebilling");
  const canManage = useCan("projects.manage");
  const refresh = useRefresh();
  const [editing, setEditing] = useState<Milestone | "new" | null>(null);
  const [removing, setRemoving] = useState<Milestone | null>(null);
  const list = useQuery({
    queryKey: ["timebilling", "milestones", project.id],
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/projects/{project_id}/milestones", { params: { path: { project_id: project.id } } })),
  });
  const mark = useMutation({
    mutationFn: (m: Milestone) => unwrap(api.PATCH("/api/v1/timebilling/milestones/{milestone_id}", { params: { path: { milestone_id: m.id } }, body: { status: m.status === "ready" ? "planned" : "ready" } })),
    onSuccess: () => void refresh(),
  });
  const remove = useMutation({
    mutationFn: (m: Milestone) => unwrap(api.DELETE("/api/v1/timebilling/milestones/{milestone_id}", { params: { path: { milestone_id: m.id } } })),
    onSuccess: () => { setRemoving(null); void refresh(); },
  });
  const sum = (list.data ?? []).reduce((s, m) => s + Number(m.amount), 0);
  const differs = !!project.fixed_fee && !!list.data?.length && Math.abs(sum - Number(project.fixed_fee)) > 0.005;
  const add = canManage && <Button onClick={() => setEditing("new")}><Plus className="h-4 w-4" />{t("milestones.add")}</Button>;

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted">{t("milestones.hint")}</p>
      {differs && <Alert tone="warn">{t("milestones.differs", { total: money(sum, currency), fee: money(project.fixed_fee, currency) })}</Alert>}
      <DataTable
        rows={list.data} loading={list.isLoading} error={list.error?.message} onRetry={() => void list.refetch()} rowKey={(m) => m.id}
        toolbar={add || undefined}
        empty={{ title: t("milestones.empty"), hint: t("milestones.emptyHint"), action: add || undefined }}
        columns={[
          { header: t("milestones.name"), cell: (m) => <span className="font-medium">{m.name}</span> },
          { header: t("milestones.due"), hideBelow: "sm", cell: (m) => formatDate(m.due_on) },
          { header: t("milestones.amount"), align: "right", cell: (m) => <span className="tnum">{money(m.amount, currency)}</span> },
          { header: t("status"), cell: (m) => <Badge tone={m.status === "ready" ? "ok" : m.status === "planned" ? "neutral" : "info"}>{t(`milestones.status.${m.status}`, m.status)}</Badge> },
          {
            header: "", align: "right",
            cell: (m) => canManage && (m.status === "planned" || m.status === "ready") ? (
              <span className="flex justify-end gap-1">
                <Button size="sm" variant="secondary" loading={mark.isPending && mark.variables?.id === m.id} onClick={() => mark.mutate(m)}>{m.status === "ready" ? t("milestones.unready") : t("milestones.ready")}</Button>
                <IconButton label={t("edit")} onClick={() => setEditing(m)}><Pencil className="h-4 w-4" /></IconButton>
                <IconButton label={t("delete")} onClick={() => setRemoving(m)}><Trash2 className="h-4 w-4" /></IconButton>
              </span>
            ) : null,
          },
        ]} />
      <MilestoneDialog project={project} milestone={editing === "new" ? null : editing} open={!!editing} onClose={() => setEditing(null)} />
      <ConfirmDialog open={!!removing} onClose={() => setRemoving(null)} onConfirm={() => removing && remove.mutate(removing)} busy={remove.isPending} danger
        title={t("delete")} message={t("milestones.deleteAsk", { name: removing?.name ?? "" })} confirmLabel={t("delete")} />
    </div>
  );
}

function MilestoneDialog({ project, milestone, open, onClose }: { project: Project; milestone: Milestone | null; open: boolean; onClose: () => void }) {
  const { t } = useTranslation("timebilling");
  const refresh = useRefresh();
  const f = useFormState({ name: "", amount: "", due: "" });
  const { reset, set } = f;
  useEffect(() => {
    if (!open) return;
    reset();
    if (milestone) { set("name", milestone.name); set("amount", milestone.amount); set("due", milestone.due_on ?? ""); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, milestone?.id]);
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => {
      const body = { name: f.values.name.trim(), amount: f.values.amount, due_on: f.values.due || null, sort_order: milestone?.sort_order ?? 0 };
      return milestone
        ? unwrap(api.PATCH("/api/v1/timebilling/milestones/{milestone_id}", { params: { path: { milestone_id: milestone.id } }, body }))
        : unwrap(api.POST("/api/v1/timebilling/projects/{project_id}/milestones", { params: { path: { project_id: project.id } }, body }));
    },
    onSuccess: () => { void refresh(); toast(t("milestones.saved"), "ok"); onClose(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  return (
    <Modal open={open} onClose={onClose} title={t(milestone ? "milestones.edit" : "milestones.add")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="milestone-form" loading={save.isPending}>{t("save")}</Button></>}>
      <form id="milestone-form" onSubmit={submit} className="space-y-4">
        <Field label={t("milestones.name")} required error={f.error("name")}><Input {...f.bind("name")} maxLength={200} required placeholder={t("milestones.nameHint")} /></Field>
        <FormGrid>
          <Field label={t("milestones.amount")} required error={f.error("amount")}><NumberInput value={f.values.amount} onChange={(v) => f.set("amount", v)} required /></Field>
          <Field label={t("milestones.due")} error={f.error("due_on")}><Input type="date" {...f.bind("due")} /></Field>
        </FormGrid>
      </form>
    </Modal>
  );
}
