import { useState } from "react";

import { Alert, Badge, Button, type Column, DataTable, ErrorState, Field, Modal, type Schemas, Skeleton, Textarea, toast, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { reasonOk } from "../../lib";
import { useOperatorCan } from "../../me";
import { useChange } from "../../stepUp";
import { useRefreshOperator } from "../billing/invoiceDialogs";
import { useBusiness } from "./useBusiness";

type BusinessUnit = Schemas["BusinessUnit"];

/** The business's units: switch one on or off with a reason (written to the business's own audit log). */
export function UnitsTab({ code }: { code: string }) {
  const { t } = useTranslation("operator");
  const canSwitch = useOperatorCan("platform.units");
  const refresh = useRefreshOperator();
  const business = useBusiness(code);
  const [switching, setSwitching] = useState<{ unit: BusinessUnit; enable: boolean } | null>(null);

  if (business.isPending) return <div className="space-y-3"><Skeleton className="h-8 w-64" /><Skeleton className="h-40 w-full" /></div>;
  if (business.isError) return <ErrorState title={t("business.loadFailed")} message={business.error.message} onRetry={() => void business.refetch()} />;
  const b = business.data;

  const columns: Column<BusinessUnit>[] = [
    { header: t("business.unit"), sortValue: (u) => u.title, cell: (u) => (
      <div className="min-w-0">
        <p className="truncate font-medium">{u.title}</p>
        <p className="truncate font-mono text-xs text-muted">{u.name}</p>
      </div>
    ) },
    { header: t("business.kind"), hideBelow: "md", cell: (u) => <span className="text-xs text-muted">{u.kind}{u.category ? ` · ${u.category}` : ""}</span> },
    { header: t("business.state"), sortValue: (u) => (u.enabled ? 0 : u.has_data ? 1 : 2), cell: (u) => (
      u.enabled ? <Badge tone="ok">{t("business.on")}</Badge> : u.has_data ? <Badge tone="neutral">{t("business.offKept")}</Badge> : <Badge tone="neutral">{t("business.off")}</Badge>
    ) },
    { header: "", align: "right", cell: (u) => {
      if (!canSwitch) return null;
      if (u.enabled) {
        return <Button size="sm" variant="secondary" disabled={!u.can_disable} title={u.why_not_disable ?? undefined} onClick={() => setSwitching({ unit: u, enable: false })}>{t("business.switchOff")}</Button>;
      }
      return <Button size="sm" disabled={!u.can_enable} title={u.can_enable ? undefined : t("business.notInstalled")} onClick={() => setSwitching({ unit: u, enable: true })}>{t("business.switchOn")}</Button>;
    } },
  ];

  return (
    <>
      {b.error && <Alert tone="bad" className="mb-4">{t("business.unreadable", { error: b.error })}</Alert>}
      {b.behind && <Alert tone="warn" className="mb-4">{t("business.behind", { units: Object.keys(b.behind_units).join(", ") })}</Alert>}
      {b.status !== "active"
        ? <p className="text-sm text-muted">{t("business.notActive")}</p>
        : <DataTable rows={b.units} columns={columns} rowKey={(u) => u.name} searchText={(u) => `${u.title} ${u.name}`} searchPlaceholder={t("business.searchUnits")} empty={{ title: t("business.noUnits") }} pageSize={20} />}
      {switching && <SwitchDialog code={b.code} unit={switching.unit} enable={switching.enable} onClose={() => setSwitching(null)} onDone={refresh} />}
    </>
  );
}

function SwitchDialog({ code, unit, enable, onClose, onDone }: { code: string; unit: BusinessUnit; enable: boolean; onClose: () => void; onDone: () => void }) {
  const { t } = useTranslation("operator");
  const [reason, setReason] = useState("");
  const change = useChange(
    () => {
      const params = { params: { path: { code, unit: unit.name } }, body: { reason: reason.trim() } };
      return opUnwrap(enable
        ? opApi.POST("/api/v1/operator/businesses/{code}/units/{unit}/enable", params)
        : opApi.POST("/api/v1/operator/businesses/{code}/units/{unit}/disable", params));
    },
    {
      onSuccess: (result) => {
        toast(t(enable ? "business.switchedOn" : "business.switchedOff", { unit: unit.title, extra: result.also_enabled.filter((n) => n !== unit.name).join(", ") }), "ok");
        onDone();
        onClose();
      },
    },
  );
  return (
    <Modal open onClose={onClose} title={t(enable ? "business.switchOnTitle" : "business.switchOffTitle", { unit: unit.title })} size="sm"
      footer={<>
        <Button variant="secondary" onClick={onClose}>{t("cancel")}</Button>
        <Button type="submit" form="switch-form" variant={enable ? "primary" : "danger"} loading={change.isPending} disabled={!reasonOk(reason)}>{t(enable ? "business.switchOn" : "business.switchOff")}</Button>
      </>}>
      <form id="switch-form" className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (reasonOk(reason)) change.mutate(undefined); }}>
        {enable && unit.will_also_enable.length > 0 && <Alert tone="info">{t("business.alsoSwitchesOn", { list: unit.will_also_enable.join(", ") })}</Alert>}
        {!enable && <p className="text-sm text-muted">{t("business.dataKept")}</p>}
        <Field label={t("business.reason")} hint={t("business.reasonHint")} required>
          <Textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} maxLength={500} autoFocus />
        </Field>
      </form>
    </Modal>
  );
}
