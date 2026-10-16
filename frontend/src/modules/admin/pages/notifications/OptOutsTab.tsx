import { Plus, Trash2 } from "lucide-react";
import { type FormEvent, useState } from "react";

import {
  api, Button, ConfirmDialog, DataTable, Drawer, Field, humanise, Input, Pager, Select, toast, unwrap, useChannels, useFormState, useMutation, usePagedList,
  useQueryClient, useTranslation, type Schemas,
} from "@/sdk";

type OptOut = Schemas["OptOutOut"];

export default function OptOutsTab({ companyId }: { companyId: string | undefined }) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [removing, setRemoving] = useState<OptOut | null>(null);
  const list = usePagedList(["optouts", companyId], (limit, offset) => unwrap(api.GET("/api/v1/notifications/opt-outs", { params: { query: { company_id: companyId!, limit, offset } } })), 25, !!companyId);
  const remove = useMutation({
    mutationFn: (o: OptOut) => unwrap(api.DELETE("/api/v1/notifications/opt-outs/{optout_id}", { params: { path: { optout_id: o.id }, query: { company_id: companyId! } } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["optouts"] }); toast(t("optOutRemoved"), "ok"); setRemoving(null); },
  });
  if (!companyId) return null;
  return (
    <>
      <p className="mb-3 text-sm text-muted">{t("optOutsHint")}</p>
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(o) => o.id}
        toolbar={<Button className="ml-auto" onClick={() => setCreating(true)}><Plus className="h-4 w-4" />{t("addOptOut")}</Button>}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
        empty={{ title: t("noOptOuts"), hint: t("noOptOutsHint") }}
        columns={[
          { header: t("recipient"), cell: (o) => <span className="tnum font-medium">{o.recipient}</span> },
          { header: t("channel"), hideBelow: "sm", cell: (o) => (o.channel ? humanise(o.channel) : t("allChannels")) },
          { header: t("reason"), hideBelow: "md", cell: (o) => o.reason ?? "—" },
          { header: "", align: "right", cell: (o) => <Button size="sm" variant="ghost" aria-label={t("remove")} onClick={() => setRemoving(o)}><Trash2 className="h-4 w-4" /></Button> },
        ]}
      />
      <AddOptOut open={creating} companyId={companyId} onClose={() => setCreating(false)} />
      <ConfirmDialog open={!!removing} onClose={() => setRemoving(null)} busy={remove.isPending} title={t("removeOptOut")} confirmLabel={t("remove")}
        message={t("removeOptOutAsk", { who: removing?.recipient })} onConfirm={() => removing && remove.mutate(removing)} />
    </>
  );
}

function AddOptOut({ open, companyId, onClose }: { open: boolean; companyId: string; onClose: () => void }) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const available = useChannels(companyId).data ?? [];
  const f = useFormState({ recipient: "", channel: "", reason: "" });
  const create = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/notifications/opt-outs", { body: {
      company_id: companyId, recipient: f.values.recipient.trim(), channel: f.values.channel || null, reason: f.values.reason.trim() || null,
    } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["optouts"] }); toast(t("optOutAdded"), "ok"); f.reset(); onClose(); },
    onError: (e) => { f.fail(e); toast(e.message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); create.mutate(); };
  return (
    <Drawer open={open} onClose={onClose} title={t("addOptOut")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="new-optout" loading={create.isPending}>{t("save")}</Button></>}>
      <form id="new-optout" onSubmit={submit} className="space-y-4">
        <Field label={t("recipient")} hint={t("recipientHint")} required error={f.error("recipient")}><Input {...f.bind("recipient")} required maxLength={200} autoFocus /></Field>
        <Field label={t("channel")} error={f.error("channel")}>
          <Select {...f.bind("channel")}><option value="">{t("allChannels")}</option>{available.map((c) => <option key={c.channel} value={c.channel}>{c.label}</option>)}</Select>
        </Field>
        <Field label={t("reason")} error={f.error("reason")}><Input {...f.bind("reason")} maxLength={300} /></Field>
      </form>
    </Drawer>
  );
}
