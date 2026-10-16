import { useState } from "react";

import { Alert, Badge, Button, Card, DetailList, Field, formatDate, Input, money, type Schemas, StatusBadge, Textarea, toast, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { Meter, SubscriptionBadge } from "../../components/bits";
import { ChangeConfirm } from "../../components/ChangeConfirm";
import { bytesLabel, splitList } from "../../helpers/format";
import { useOperatorCan } from "../../me";
import { useChange } from "../../stepUp";

type Detail = Schemas["SubscriberDetail"];

export function OverviewTab({ d, onSaved }: { d: Detail; onSaved: (detail: Detail) => void }) {
  const { t } = useTranslation("operator");
  const canManage = useOperatorCan("platform.subscribers");
  const [cancelling, setCancelling] = useState(false);
  const s = d.subscription;
  const unlimited = t("subscriber.unlimited");

  return (
    <div className="space-y-4">
      {d.deletion && (
        <Alert tone="bad">
          <p className="font-medium">{t("subscriber.deletion.scheduled", { date: formatDate(d.deletion.execute_after, true) })}</p>
          <p className="text-xs">{t("subscriber.deletion.by", { name: d.deletion.requested_by, date: formatDate(d.deletion.requested_at), reason: d.deletion.reason })}</p>
          {canManage && <Button className="mt-2" size="sm" variant="secondary" onClick={() => setCancelling(true)}>{t("subscriber.deletion.cancel")}</Button>}
        </Alert>
      )}
      {d.message && <Alert tone={d.access === "full" ? "ok" : "warn"}>{d.message}</Alert>}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title={t("subscriber.profile")} className="lg:col-span-1">
          <DetailList items={[
            { label: t("subs.status"), value: <SubscriptionBadge status={d.status} /> },
            { label: t("subscriber.businessState"), value: <StatusBadge status={d.tenant_status} /> },
            { label: t("subs.edition"), value: d.edition ?? "-" },
            { label: t("subs.country"), value: d.country ?? "-" },
            { label: t("subs.created"), value: formatDate(d.created_at) },
            { label: t("subs.lastActivity"), value: d.last_activity ? formatDate(d.last_activity, true) : "-" },
          ]} />
          <h3 className="mb-2 mt-4 text-xs font-medium uppercase tracking-wide text-muted">{t("subscriber.owners")}</h3>
          {d.owners.length === 0 ? <p className="text-sm text-muted">{t("subscriber.noOwners")}</p> : (
            <ul className="space-y-2">
              {d.owners.map((o) => (
                <li key={`${o.name}${o.email}`} className="text-sm"><p className="font-medium">{o.name}</p><p className="text-xs text-muted">{[o.email, o.phone].filter(Boolean).join(" · ")}</p></li>
              ))}
            </ul>
          )}
        </Card>

        <Card title={t("subscriber.subscription")} className="lg:col-span-2">
          {!s ? <p className="text-sm text-muted">{t("subscriber.noSubscription")}</p> : (
            <DetailList items={[
              { label: t("subs.plan"), value: <span>{s.plan_name} <span className="font-mono text-xs text-muted">{s.plan_code}</span></span> },
              { label: t("subscriber.price"), value: `${money(s.unit_amount, s.currency)} / ${t(`interval.${s.interval}`)}${s.tax_inclusive ? ` (${t("subscriber.taxIncluded")})` : ""}` },
              { label: t("subscriber.periodStart"), value: s.period_start ? formatDate(s.period_start) : "-" },
              { label: t("subscriber.periodEnd"), value: s.period_end ? formatDate(s.period_end) : "-" },
              { label: t("subscriber.trialEnd"), value: s.trial_end ? formatDate(s.trial_end) : "-" },
              {
                label: t("subscriber.flags"),
                value: (
                  <span className="flex flex-wrap gap-1">
                    {s.is_comp && <Badge tone="brand">{t("subs.comp")}</Badge>}
                    {s.cancel_at_period_end && <Badge tone="warn">{t("subs.cancelling")}</Badge>}
                    {s.pending_plan_id && <Badge tone="info">{t("subscriber.planChangeScheduled")}</Badge>}
                    {s.coupon_periods_left !== null && <Badge tone="ok">{t("subscriber.couponLeft", { count: s.coupon_periods_left })}</Badge>}
                    {!s.is_comp && !s.cancel_at_period_end && !s.pending_plan_id && s.coupon_periods_left === null && "-"}
                  </span>
                ),
              },
              ...(s.status_reason ? [{ label: t("subscriber.statusReason"), value: `${s.status_reason} (${formatDate(s.status_changed_at)})` }] : []),
              { label: t("subscriber.since"), value: formatDate(s.created_at) },
            ]} />
          )}
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={t("subscriber.usage")} description={t("subscriber.usageHint")}>
          <div className="space-y-3">
            <Meter label={t("subscriber.users")} used={d.usage.users} limit={d.limits.users} unlimited={unlimited} />
            <Meter label={t("subscriber.branches")} used={d.usage.branches} limit={d.limits.branches} unlimited={unlimited} />
            <Meter label={t("subscriber.companies")} used={d.usage.companies} limit={d.limits.companies} unlimited={unlimited} />
            <DetailList items={[
              { label: t("subscriber.storage"), value: bytesLabel(d.usage.storage_bytes) },
              { label: t("subscriber.failedJobs"), value: <span className={d.usage.failed_jobs > 0 ? "text-bad" : undefined}>{d.usage.failed_jobs}</span> },
            ]} />
          </div>
        </Card>
        {s ? <NotesCard key={`${s.notes}|${s.tags.join(",")}`} d={d} editable={canManage} onSaved={onSaved} /> : <Card title={t("subscriber.notes")}><p className="text-sm text-muted">{t("subscriber.notesNeedSubscription")}</p></Card>}
      </div>

      {cancelling && (
        <ChangeConfirm title={t("subscriber.deletion.cancelTitle")} message={<p>{t("subscriber.deletion.cancelMessage")}</p>} confirmLabel={t("subscriber.deletion.cancel")}
          run={() => opUnwrap(opApi.DELETE("/api/v1/operator/subscribers/{code}/delete", { params: { path: { code: d.code } } }))}
          onDone={(detail) => { toast(t("subscriber.deletion.cancelled"), "ok"); onSaved(detail); }} onClose={() => setCancelling(false)} />
      )}
    </div>
  );
}

function NotesCard({ d, editable, onSaved }: { d: Detail; editable: boolean; onSaved: (detail: Detail) => void }) {
  const { t } = useTranslation("operator");
  const [notes, setNotes] = useState(d.subscription?.notes ?? "");
  const [tags, setTags] = useState((d.subscription?.tags ?? []).join(", "));
  const dirty = notes !== (d.subscription?.notes ?? "") || tags !== (d.subscription?.tags ?? []).join(", ");
  const save = useChange(
    () => opUnwrap(opApi.PATCH("/api/v1/operator/subscribers/{code}/notes", { params: { path: { code: d.code } }, body: { notes, tags: splitList(tags) } })),
    { onSuccess: (detail) => { toast(t("subscriber.notesSaved"), "ok"); onSaved(detail); } },
  );
  return (
    <Card title={t("subscriber.notes")} description={t("subscriber.notesHint")}>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (dirty && !save.isPending) save.mutate(undefined); }}>
        <Field label={t("subscriber.notes")}><Textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={4} maxLength={4000} disabled={!editable} /></Field>
        <Field label={t("subscriber.tags")} hint={t("subscriber.tagsHint")}><Input value={tags} onChange={(e) => setTags(e.target.value)} disabled={!editable} /></Field>
        {editable && <div className="flex justify-end"><Button type="submit" size="sm" loading={save.isPending} disabled={!dirty}>{t("subscriber.saveNotes")}</Button></div>}
      </form>
    </Card>
  );
}
