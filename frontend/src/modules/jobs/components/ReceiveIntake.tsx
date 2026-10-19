import { Field, FormGrid, Input, NumberInput, Select, Textarea, useTranslation } from "@/sdk";

import { useJobTypes } from "../hooks";
import type { ReceiveForm } from "../receive";

const FUEL = ["empty", "1/4", "1/2", "3/4", "full"] as const;

/** What the counter notes at drop-off: the kind of job, the odometer, the fuel, the key tag, belongings, and who signed for it. */
export function ReceiveIntake({ companyId, form, update, hint }: { companyId: string; form: ReceiveForm; update: (patch: Partial<ReceiveForm>) => void; hint?: string }) {
  const { t } = useTranslation("jobs");
  const types = useJobTypes(companyId, true);
  return (
    <div className="space-y-4">
      {(types.data ?? []).length > 0 && (
        <Field label={t("garage.receive.jobType")} hint={t("garage.receive.jobTypeHint")}>
          <Select className="h-11" value={form.jobTypeCode} onChange={(e) => update({ jobTypeCode: e.target.value })}>
            <option value="">{t("garage.receive.noJobType")}</option>
            {(types.data ?? []).map((k) => <option key={k.id} value={k.code}>{k.name}</option>)}
          </Select>
        </Field>
      )}
      <FormGrid>
        <Field label={t("garage.workshop.odometerIn")} hint={hint}><NumberInput className="h-11" value={form.odometer} onChange={(v) => update({ odometer: v })} /></Field>
        <Field label={t("garage.workshop.fuel")}>
          <Input className="h-11" list="jobs-fuel" maxLength={40} value={form.fuel} onChange={(e) => update({ fuel: e.target.value })} />
          <datalist id="jobs-fuel">{FUEL.map((f) => <option key={f} value={f} />)}</datalist>
        </Field>
        <Field label={t("garage.workshop.keyTag")}><Input className="h-11" maxLength={40} value={form.keyTag} onChange={(e) => update({ keyTag: e.target.value })} /></Field>
        <Field label={t("garage.workshop.signedBy")} hint={t("garage.workshop.signedByHint")}><Input className="h-11" maxLength={160} value={form.signedBy} onChange={(e) => update({ signedBy: e.target.value })} /></Field>
      </FormGrid>
      <Field label={t("garage.workshop.belongings")} hint={t("garage.receive.belongingsHint")}><Textarea maxLength={1000} value={form.belongings} onChange={(e) => update({ belongings: e.target.value })} /></Field>
    </div>
  );
}
