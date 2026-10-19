import { useEffect, useState } from "react";

import { api, Alert, Button, Card, Field, NumberInput, Select, unwrap, useTranslation } from "@/sdk";

import { useClaimsMutation } from "../hooks";
import type { Settings } from "../types";
import { ServiceItemPicker } from "./pickers";

/** The claim settings of a company: the service item invoices are made under, what to do with unapproved work, how long things last. */
export function SettingsCard({ settings, canEdit }: { settings: Settings; canEdit: boolean }) {
  const { t } = useTranslation("claims");
  const [f, setF] = useState({ item: settings.invoice_product_id ?? "", policy: settings.unapproved_work, valid: String(settings.estimate_valid_days), link: String(settings.link_valid_days), tolerance: settings.short_pay_tolerance });
  useEffect(() => { setF({ item: settings.invoice_product_id ?? "", policy: settings.unapproved_work, valid: String(settings.estimate_valid_days), link: String(settings.link_valid_days), tolerance: settings.short_pay_tolerance }); }, [settings]);
  const save = useClaimsMutation(() => unwrap(api.PATCH("/api/v1/claims/settings", { params: { query: { company_id: settings.company_id } }, body: {
    invoice_product_id: f.item || null, unapproved_work: f.policy as "warn" | "block", estimate_valid_days: Number(f.valid) || 14, link_valid_days: Number(f.link) || 14, short_pay_tolerance: String(f.tolerance) || "0" } })),
  { done: t("settings.saved") });
  return (
    <Card title={t("settings.title")} description={t("settings.hint")} actions={canEdit && <Button size="sm" loading={save.isPending} onClick={() => save.mutate(undefined)}>{t("common.save")}</Button>}>
      <div className="space-y-4">
        {!settings.invoice_product_id && <Alert tone="warn">{t("settings.itemMissing")}</Alert>}
        <div className="grid gap-4 md:grid-cols-2">
          <Field label={t("settings.item")} hint={t("settings.itemHint")}>
            <div>
              {settings.invoice_product_name && f.item === settings.invoice_product_id && <p className="mb-1 text-sm font-medium">{settings.invoice_product_name}</p>}
              <ServiceItemPicker value={f.item} onChange={(v) => setF({ ...f, item: v })} disabled={!canEdit} />
            </div>
          </Field>
          <Field label={t("settings.unapproved")} hint={t("settings.unapprovedHint")}>
            <Select value={f.policy} disabled={!canEdit} onChange={(e) => setF({ ...f, policy: e.target.value })}>
              <option value="warn">{t("settings.warn")}</option>
              <option value="block">{t("settings.block")}</option>
            </Select>
          </Field>
          <Field label={t("settings.valid")} hint={t("settings.validHint")}><NumberInput value={f.valid} disabled={!canEdit} inputMode="numeric" onChange={(v) => setF({ ...f, valid: v })} /></Field>
          <Field label={t("settings.link")} hint={t("settings.linkHint")}><NumberInput value={f.link} disabled={!canEdit} inputMode="numeric" onChange={(v) => setF({ ...f, link: v })} /></Field>
          <Field label={t("settings.tolerance")} hint={t("settings.toleranceHint")}><NumberInput value={String(f.tolerance)} disabled={!canEdit} inputMode="decimal" onChange={(v) => setF({ ...f, tolerance: v })} /></Field>
        </div>
      </div>
    </Card>
  );
}
