import { useState } from "react";

import { Badge, type BadgeTone, Button, type Column, DataTable, Field, formatDate, money, type Schemas, Select, Textarea, toast, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { usePlatformUnits } from "../../catalog";
import { ActionForm } from "../../components/ActionForm";
import { ReasonDialog } from "../../components/ReasonDialog";
import { sellableUnits } from "../../helpers/planUnits";
import { reasonOk } from "../../lib";
import { useOperatorCan } from "../../me";

type Detail = Schemas["SubscriberDetail"];
type Addon = Schemas["SubscriberAddonOut"];
const TONES: Record<string, BadgeTone> = { active: "ok", pending: "warn", revoked: "bad", void: "neutral" };

/** What this business bought or was given on top of its plan; an operator may give one (with a reason) or take one back. */
export function AddonsSection({ d, onSaved }: { d: Detail; onSaved: (detail: Detail) => void }) {
  const { t } = useTranslation("operator");
  const can = useOperatorCan("platform.subscribers");
  const [dialog, setDialog] = useState<"grant" | Addon | null>(null);
  const columns: Column<Addon>[] = [
    { header: t("subscriber.addons.unit"), cell: (a) => <div className="min-w-0"><p className="truncate text-sm font-medium">{a.title}</p><p className="truncate font-mono text-xs text-muted">{a.unit_name}</p></div> },
    { header: t("billing.invoice.status"), cell: (a) => <Badge tone={TONES[a.status] ?? "neutral"}>{t(`subscriber.addons.statuses.${a.status}`, a.status)}</Badge> },
    { header: t("subscriber.addons.how"), hideBelow: "sm", cell: (a) => (
      <div className="text-sm">{a.granted_by === "operator" ? t("subscriber.addons.given") : a.currency ? money(a.price, a.currency) : "-"}
        {a.invoice_number && <p className="font-mono text-xs text-muted">{a.invoice_number}</p>}
        {a.reason && <p className="text-xs text-muted">{a.reason}</p>}
        {a.revoke_reason && <p className="text-xs text-bad">{a.revoke_reason}</p>}</div>
    ) },
    { header: t("subscriber.addons.when"), hideBelow: "md", cell: (a) => <span className="text-sm">{a.purchased_at ? formatDate(a.purchased_at) : "-"}</span> },
    { header: "", align: "right", cell: (a) => can && (a.status === "active" || a.status === "pending")
      ? <Button size="sm" variant="secondary" onClick={() => setDialog(a)}>{t("subscriber.addons.revoke")}</Button> : null },
  ];
  return (
    <section>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold">{t("subscriber.addons.title")}</h2>
        {can && <Button size="sm" onClick={() => setDialog("grant")}>{t("subscriber.addons.give")}</Button>}
      </div>
      <p className="mb-2 text-xs text-muted">{t("subscriber.addons.hint")}</p>
      <DataTable rows={d.addons} columns={columns} rowKey={(a) => a.id} dense pageSize={10} empty={{ title: t("subscriber.addons.none") }} />
      {dialog === "grant" && <GrantDialog d={d} onDone={(detail) => { onSaved(detail); toast(t("subscriber.addons.given_done"), "ok"); }} onClose={() => setDialog(null)} />}
      {dialog && dialog !== "grant" && (
        <ReasonDialog title={t("subscriber.addons.revokeTitle", { name: dialog.title })} intro={t("subscriber.addons.revokeMessage")} confirmLabel={t("subscriber.addons.revoke")} danger
          run={(reason) => opUnwrap(opApi.POST("/api/v1/operator/subscribers/{code}/addons/{unit}/revoke", { params: { path: { code: d.code, unit: dialog.unit_name } }, body: { reason } }))}
          onDone={(detail) => { onSaved(detail); toast(t("subscriber.addons.revoked"), "ok"); }} onClose={() => setDialog(null)} />
      )}
    </section>
  );
}

function GrantDialog({ d, onDone, onClose }: { d: Detail; onDone: (detail: Detail) => void; onClose: () => void }) {
  const { t } = useTranslation("operator");
  const units = usePlatformUnits();
  const [unit, setUnit] = useState("");
  const [reason, setReason] = useState("");
  const have = new Set(d.addons.filter((a) => a.status === "active").map((a) => a.unit_name));
  const options = sellableUnits(units.data ?? []).filter((u) => !have.has(u.name));
  return (
    <ActionForm title={t("subscriber.addons.giveTitle")} submitLabel={t("subscriber.addons.give")} ready={!!unit && reasonOk(reason)} onDone={onDone} onClose={onClose}
      run={() => opUnwrap(opApi.POST("/api/v1/operator/subscribers/{code}/addons", { params: { path: { code: d.code } }, body: { unit, reason: reason.trim() } }))}>
      <p className="text-sm text-muted">{t("subscriber.addons.giveMessage")}</p>
      <Field label={t("subscriber.addons.unit")} required>
        <Select value={unit} onChange={(e) => setUnit(e.target.value)}>
          <option value="">{t("subscriber.addons.choose")}</option>
          {options.map((u) => <option key={u.name} value={u.name}>{u.title}</option>)}
        </Select>
      </Field>
      <Field label={t("common.reason")} required><Textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} maxLength={500} /></Field>
    </ActionForm>
  );
}
