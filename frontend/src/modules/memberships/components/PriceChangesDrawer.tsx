import { useState } from "react";

import {
  api, Badge, Button, DataTable, Drawer, Field, formatDate, Input, money, NumberInput, Switch, toast, today, unwrap, useCan, useCurrency, useMutation, useQuery, useQueryClient,
  useTranslation,
} from "@/sdk";

import type { Plan } from "../hooks";

/** Prices that change from a date: what is booked, add a change, cancel one. A change never reaches back to invoices already made. */
export function PriceChangesDrawer({ plan, onClose }: { plan: Plan | null; onClose: () => void }) {
  const { t } = useTranslation("memberships");
  const qc = useQueryClient();
  const canEdit = useCan("memberships.plans");
  const currency = useCurrency(plan?.company_id);
  const [from, setFrom] = useState("");
  const [fee, setFee] = useState("");
  const [existing, setExisting] = useState(false);
  const [note, setNote] = useState("");
  const list = useQuery({
    enabled: !!plan, queryKey: ["memberships-price-changes", plan?.id],
    queryFn: () => unwrap(api.GET("/api/v1/memberships/plans/{plan_id}/price-changes", { params: { path: { plan_id: plan?.id ?? "" } } })),
  });
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["memberships-price-changes"] }); void qc.invalidateQueries({ queryKey: ["memberships-plans"] }); };
  const add = useMutation({
    meta: { silent: true }, onError: (e) => toast((e as Error).message, "bad"),
    mutationFn: () => unwrap(api.POST("/api/v1/memberships/plans/{plan_id}/price-changes", { params: { path: { plan_id: plan?.id ?? "" } }, body: { effective_from: from, fee, apply_to_existing: existing, note: note.trim() || null } })),
    onSuccess: () => { refresh(); toast(t("priceChange.added"), "ok"); setFrom(""); setFee(""); setNote(""); setExisting(false); },
  });
  const cancel = useMutation({
    meta: { silent: true }, onError: (e) => toast((e as Error).message, "bad"),
    mutationFn: (id: string) => unwrap(api.POST("/api/v1/memberships/price-changes/{change_id}/cancel", { params: { path: { change_id: id } } })),
    onSuccess: () => { refresh(); toast(t("priceChange.cancelled"), "ok"); },
  });
  return (
    <Drawer open={!!plan} onClose={onClose} title={t("priceChange.title", { name: plan?.name ?? "" })}>
      <div className="space-y-5">
        <p className="text-sm text-muted">{t("priceChange.explain", { fee: money(plan?.current_fee ?? 0, currency) })}</p>
        <DataTable rows={list.data} loading={list.isLoading} error={list.error?.message} onRetry={() => void list.refetch()} rowKey={(c) => c.id} dense
          empty={{ title: t("priceChange.empty") }}
          columns={[
            { header: t("priceChange.from"), cell: (c) => formatDate(c.effective_from) },
            { header: t("fee"), align: "right", cell: (c) => money(c.fee, currency) },
            { header: t("status"), cell: (c) => <Badge tone={c.status === "scheduled" ? "info" : "neutral"}>{t(`priceChange.status.${c.status}`, c.status)}</Badge> },
            { header: "", align: "right", cell: (c) => (canEdit && c.status === "scheduled" ? <Button size="sm" variant="secondary" loading={cancel.isPending} onClick={() => cancel.mutate(c.id)}>{t("priceChange.cancel")}</Button> : null) },
          ]} />
        {canEdit && (
          <form className="space-y-4 rounded-lg border border-line p-4" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
            <p className="font-semibold">{t("priceChange.add")}</p>
            <Field label={t("priceChange.from")} required><Input type="date" min={today()} value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
            <Field label={t("priceChange.newFee")} required><NumberInput value={fee} onChange={setFee} /></Field>
            <Switch checked={existing} onChange={setExisting} label={t("priceChange.existing")} />
            <p className="text-xs text-muted">{t("priceChange.existingHint")}</p>
            <Field label={t("note")}><Input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} /></Field>
            <Button type="submit" loading={add.isPending} disabled={!from || !fee}>{t("priceChange.schedule")}</Button>
          </form>
        )}
      </div>
    </Drawer>
  );
}
