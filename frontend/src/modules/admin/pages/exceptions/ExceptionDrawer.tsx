import { useState } from "react";

import {
  api, Alert, Badge, Button, DetailList, Drawer, ErrorState, Field, formatDate, humanise, money, Select, SkeletonRows, StatusBadge, Textarea, toast, unwrap,
  useCan, useCurrency, useMutation, useQuery, useQueryClient, useSession, useTranslation, type Schemas,
} from "@/sdk";

import { EXCEPTION_STATUSES, SEVERITY_TONE } from "./constants";

type Item = Schemas["ExceptionItemOut"];
// What an item may become next (the server enforces the same rules).
const NEXT: Record<string, string[]> = { open: ["explained", "resolved", "dismissed"], explained: ["resolved", "dismissed"], resolved: [], dismissed: [] };

export default function ExceptionDrawer({ id, onClose }: { id: string | null; onClose: () => void }) {
  const { t } = useTranslation("kernel");
  const item = useQuery({ enabled: !!id, queryKey: ["exception", id], queryFn: () => unwrap(api.GET("/api/v1/exceptions/{item_id}", { params: { path: { item_id: id! } } })) });
  return (
    <Drawer open={!!id} onClose={onClose} title={t("exceptionDetail")}>
      {item.error ? <ErrorState message={item.error.message} onRetry={() => void item.refetch()} /> : !item.data ? <SkeletonRows rows={5} cols={2} /> : <Detail item={item.data} />}
    </Drawer>
  );
}

function Detail({ item }: { item: Item }) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const { me } = useSession();
  const canUsers = useCan("users.manage");
  const currency = useCurrency(item.company_id ?? undefined);
  const users = useQuery({ enabled: canUsers, queryKey: ["users"], queryFn: () => unwrap(api.GET("/api/v1/users")) });
  const nameOf = (userId: string | null) => (!userId ? null : userId === me?.user_id ? t("you") : users.data?.find((u) => u.id === userId)?.full_name ?? t("someone"));

  const refresh = (data: Item) => { qc.setQueryData(["exception", item.id], data); void qc.invalidateQueries({ queryKey: ["exceptions"] }); void qc.invalidateQueries({ queryKey: ["exceptions-count"] }); };
  const assign = useMutation({
    mutationFn: (userId: string | null) => unwrap(api.POST("/api/v1/exceptions/{item_id}/assign", { params: { path: { item_id: item.id } }, body: { user_id: userId } })),
    onSuccess: (data) => { refresh(data); toast(t("assignedDone"), "ok"); },
  });
  const [next, setNext] = useState("");
  const [note, setNote] = useState("");
  const options = NEXT[item.status] ?? [];
  const change = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/exceptions/{item_id}/status", { params: { path: { item_id: item.id } }, body: { status: next as "resolved", note: note.trim() } })),
    onSuccess: (data) => { refresh(data); setNext(""); setNote(""); toast(t("exStatusDone"), "ok"); },
  });

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={SEVERITY_TONE[item.severity] ?? "neutral"}>{humanise(item.severity)}</Badge>
        <StatusBadge status={item.status} />
        <span className="text-sm font-medium">{humanise(item.kind)}</span>
      </div>
      <p className="text-sm">{item.message}</p>
      <DetailList items={[
        { label: t("unit"), value: humanise(item.unit_name) },
        { label: t("raised"), value: formatDate(item.created_at, true) },
        { label: t("amount"), value: item.amount == null ? null : money(item.amount, currency) },
        { label: t("source"), value: item.ref_type ? <span>{humanise(item.ref_type)}{item.ref_id && <code className="ml-1 text-xs text-muted">{item.ref_id.slice(0, 8)}</code>}</span> : null },
        { label: t("assignedTo"), value: nameOf(item.assigned_to) ?? t("unassigned") },
        ...(item.resolved_at ? [{ label: t("closedOn"), value: `${formatDate(item.resolved_at, true)} · ${nameOf(item.resolved_by) ?? ""}` }] : []),
      ]} />
      {item.resolution_note && <Alert tone="ok"><strong>{t("note")}:</strong> {item.resolution_note}</Alert>}

      {options.length > 0 && (
        <section className="space-y-3 rounded-xl bg-sunken p-4">
          <h3 className="text-sm font-semibold">{t("assign")}</h3>
          <div className="flex flex-wrap gap-2">
            {me?.user_id && item.assigned_to !== me.user_id && <Button size="sm" variant="secondary" loading={assign.isPending} onClick={() => assign.mutate(me.user_id!)}>{t("assignToMe")}</Button>}
            {item.assigned_to && <Button size="sm" variant="ghost" loading={assign.isPending} onClick={() => assign.mutate(null)}>{t("unassign")}</Button>}
          </div>
          {canUsers && (
            <Field label={t("assignToUser")}>
              <Select value="" onChange={(e) => e.target.value && assign.mutate(e.target.value)}>
                <option value="">{t("choose")}</option>
                {(users.data ?? []).filter((u) => u.status !== "disabled").map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}
              </Select>
            </Field>
          )}
        </section>
      )}

      {options.length > 0 && (
        <section className="space-y-3 rounded-xl bg-sunken p-4">
          <h3 className="text-sm font-semibold">{t("changeStatus")}</h3>
          <Field label={t("newStatus")}>
            <Select value={next} onChange={(e) => setNext(e.target.value)}>
              <option value="">{t("choose")}</option>
              {options.filter((s) => EXCEPTION_STATUSES.includes(s)).map((s) => <option key={s} value={s}>{t(`exStatus.${s}`)}</option>)}
            </Select>
          </Field>
          <Field label={t("note")} hint={t("noteRequiredHint")}><Textarea rows={3} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
          <Button loading={change.isPending} disabled={!next || !note.trim()} onClick={() => change.mutate()}>{t("save")}</Button>
        </section>
      )}
    </div>
  );
}
