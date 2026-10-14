import { Check, Plus } from "lucide-react";
import { useState } from "react";

import {
  api, Badge, Button, Card, Checkbox, DataTable, Drawer, Field, formatDate, Input, orNull, Select, Textarea, toast, unwrap, useCan, useFormState, useMutation,
  usePagedList, Pager, useQueryClient, useTranslation,
} from "@/sdk";

import { dueToIso, isOverdueActivity } from "../logic";

const KINDS = ["call", "visit", "message", "meeting", "task"] as const;

/**
 * Follow-ups (calls, visits, tasks). With `about` it lists those for one lead or customer and can add more;
 * without it, it lists the signed-in user's own.
 */
export function FollowUps({ about }: { about?: { type: "lead" | "customer"; id: string } }) {
  const { t } = useTranslation("crm");
  const qc = useQueryClient();
  const canLeads = useCan("leads.manage");
  const canCustomers = useCan("customers.manage");
  const canAdd = canLeads || canCustomers;
  const [openOnly, setOpenOnly] = useState(true);
  const [adding, setAdding] = useState(false);
  const [doneId, setDoneId] = useState<string | null>(null);
  const list = usePagedList(["activities", about?.type, about?.id, openOnly], (limit, offset) =>
    unwrap(api.GET("/api/v1/crm/activities", { params: { query: {
      related_type: about?.type, related_id: about?.id, mine: about ? undefined : true, open_only: openOnly || undefined, limit, offset } } })));
  const f = useFormState({ kind: "call", due_at: "", note: "" });
  const [doneNote, setDoneNote] = useState("");

  const add = useMutation({
    meta: { silent: true },
    mutationFn: () => {
      if (!about) throw new Error(t("pickSomeone"));
      return unwrap(api.POST("/api/v1/crm/activities", { body: {
        related_type: about.type, related_id: about.id, kind: f.values.kind as "call", due_at: dueToIso(f.values.due_at), note: orNull(f.values.note) } }));
    },
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["activities"] }); toast(t("followUpAdded"), "ok"); f.reset(); setAdding(false); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const done = useMutation({
    meta: { silent: true },
    mutationFn: (id: string) => unwrap(api.POST("/api/v1/crm/activities/{activity_id}/done", { params: { path: { activity_id: id } }, body: { note: orNull(doneNote) } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["activities"] }); toast(t("followUpDone"), "ok"); setDoneId(null); setDoneNote(""); },
    onError: (e) => toast((e as Error).message, "bad"),
  });

  const table = (
    <DataTable
      rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(a) => a.id}
      toolbar={<Checkbox label={t("openOnly")} checked={openOnly} onChange={(e) => setOpenOnly(e.target.checked)} />}
      empty={{ title: openOnly ? t("noOpenFollowUps") : t("noFollowUps"), hint: about ? t("followUpsHint") : t("myFollowUpsHint") }}
      columns={[
        { header: t("kind"), cell: (a) => <Badge tone="brand">{t(`activityKinds.${a.kind}`, a.kind)}</Badge> },
        { header: t("note"), cell: (a) => a.note ?? "—" },
        {
          header: t("due"),
          cell: (a) => (a.done_at ? <span className="text-muted">{t("doneOn", { date: formatDate(a.done_at, true) })}</span>
            : <span className={isOverdueActivity(a) ? "font-medium text-bad" : undefined}>{a.due_at ? formatDate(a.due_at, true) : "—"}</span>),
        },
        {
          header: "", align: "right",
          cell: (a) => !a.done_at && canAdd && <Button size="sm" variant="secondary" onClick={() => setDoneId(a.id)}><Check className="h-3.5 w-3.5" />{t("markDone")}</Button>,
        },
      ]}
      footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
    />
  );

  return (
    <>
      {about ? (
        <Card title={t("followUps")} flush actions={canAdd && <Button size="sm" variant="secondary" onClick={() => setAdding(true)}><Plus className="h-3.5 w-3.5" />{t("addFollowUp")}</Button>}>{table}</Card>
      ) : table}
      <Drawer open={adding} onClose={() => setAdding(false)} title={t("addFollowUp")}
        footer={<><Button variant="secondary" onClick={() => setAdding(false)}>{t("cancel")}</Button><Button type="submit" form="followup-form" loading={add.isPending}>{t("save")}</Button></>}>
        <form id="followup-form" className="space-y-4" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
          <Field label={t("kind")} error={f.error("kind")}><Select {...f.bind("kind")}>{KINDS.map((k) => <option key={k} value={k}>{t(`activityKinds.${k}`)}</option>)}</Select></Field>
          <Field label={t("due")} error={f.error("due_at")}><Input type="datetime-local" {...f.bind("due_at")} /></Field>
          <Field label={t("note")} error={f.error("note")}><Textarea {...f.bind("note")} maxLength={1000} /></Field>
        </form>
      </Drawer>
      <Drawer open={!!doneId} onClose={() => setDoneId(null)} title={t("markDone")}
        footer={<><Button variant="secondary" onClick={() => setDoneId(null)}>{t("cancel")}</Button><Button loading={done.isPending} onClick={() => doneId && done.mutate(doneId)}>{t("markDone")}</Button></>}>
        <Field label={t("outcome")} hint={t("outcomeHint")}><Textarea value={doneNote} onChange={(e) => setDoneNote(e.target.value)} maxLength={1000} /></Field>
      </Drawer>
    </>
  );
}
