import { useState } from "react";

import { api, Button, Drawer, Field, FormGrid, Input, NumberInput, Switch, Textarea, toast, unwrap, useMutation, useQueryClient, useTranslation } from "@/sdk";

import { useJobsCompany, useUnit } from "../hooks";
import { cleanIdentifiers, ITEM_KINDS, identifierRows, type IdentifierRow } from "../lib";
import type { Asset } from "../types";
import { IdentifierRows } from "./IdentifierRows";
import { CustomerPicker } from "./pickers";

/** Record an item customers bring in, or change one. Mount it only while open. */
export function ItemDrawer({ asset, onClose, onSaved }: { asset?: Asset; onClose: () => void; onSaved?: (a: Asset) => void }) {
  const { t } = useTranslation("jobs");
  const qc = useQueryClient();
  const { companyId } = useJobsCompany();
  const hasCustomers = useUnit("crm");
  const [label, setLabel] = useState(asset?.label ?? "");
  const [kind, setKind] = useState(asset?.kind ?? "");
  const [notes, setNotes] = useState(asset?.notes ?? "");
  const [customerId, setCustomerId] = useState(asset?.customer_id ?? "");
  const [rows, setRows] = useState<IdentifierRow[]>(() => identifierRows(asset?.identifiers));
  const [active, setActive] = useState(asset?.is_active ?? true);
  const [courtesy, setCourtesy] = useState(asset?.kind === "courtesy-car");
  const [nextDate, setNextDate] = useState(asset?.next_service_date ?? "");
  const [nextKm, setNextKm] = useState(asset?.next_service_odometer ?? "");

  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => {
      const common = { label: label.trim(), kind: courtesy ? "courtesy-car" : kind.trim() || "item", notes: notes.trim() || null, customer_id: customerId || null, identifiers: cleanIdentifiers(rows) };
      return asset
        ? unwrap(api.PATCH("/api/v1/jobs/assets/{asset_id}", { params: { path: { asset_id: asset.id } }, body: { ...common, is_active: active, next_service_date: nextDate || null, next_service_odometer: nextKm || null } }))
        : unwrap(api.POST("/api/v1/jobs/assets", { body: { ...common, company_id: companyId } }));
    },
    onSuccess: (saved) => { void qc.invalidateQueries({ queryKey: ["jobs"] }); toast(t(asset ? "items.saved" : "items.created"), "ok"); onSaved?.(saved); onClose(); },
    onError: (e) => toast((e as Error).message, "bad"),
  });

  return (
    <Drawer open onClose={onClose} title={t(asset ? "items.editTitle" : "items.newTitle")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button loading={save.isPending} disabled={!label.trim()} onClick={() => save.mutate()}>{t("common.save")}</Button></>}>
      <div className="space-y-4">
        <Field label={t("receive.itemLabel")} required hint={t("receive.itemLabelHint")}><Input maxLength={160} value={label} onChange={(e) => setLabel(e.target.value)} autoFocus /></Field>
        <FormGrid>
          <Field label={t("receive.itemKind")}>
            <>
              <Input list="jobs-drawer-kinds" maxLength={40} value={kind} onChange={(e) => setKind(e.target.value)} />
              <datalist id="jobs-drawer-kinds">{ITEM_KINDS.map((k) => <option key={k} value={t(`kinds.${k}`)} />)}</datalist>
            </>
          </Field>
          {hasCustomers && <Field label={t("receive.customer")}><CustomerPicker value={customerId} onChange={setCustomerId} /></Field>}
        </FormGrid>
        <Field label={t("receive.identifiers")} hint={t("receive.identifiersHint")}><IdentifierRows rows={rows} onChange={setRows} /></Field>
        {asset && (
          <FormGrid>
            <Field label={t("garage.workshop.nextServiceDate")}><Input type="date" value={nextDate} onChange={(e) => setNextDate(e.target.value)} /></Field>
            <Field label={t("garage.workshop.nextServiceOdometer")}><NumberInput value={nextKm} onChange={setNextKm} /></Field>
          </FormGrid>
        )}
        <div className="flex items-center gap-2 text-sm"><Switch checked={courtesy} onChange={setCourtesy} label={t("garage.loan.isCourtesy")} /><span>{t("garage.loan.isCourtesy")}</span></div>
        <Field label={t("items.notes")}><Textarea maxLength={1000} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
        {asset && <div className="flex items-center gap-2 text-sm"><Switch checked={active} onChange={setActive} label={t("items.active")} /><span>{t("items.active")}</span></div>}
      </div>
    </Drawer>
  );
}
