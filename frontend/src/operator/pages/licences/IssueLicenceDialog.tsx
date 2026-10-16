import { Download } from "lucide-react";
import { useState } from "react";

import { Alert, Button, Checkbox, Field, FormGrid, Input, Modal, NumberInput, type Schemas, Select, Textarea, toast, useTranslation } from "@/sdk";

import { opApi, opUnwrap, saveText } from "../../client";
import { useEditions, usePlans } from "../../catalog";
import { CopyButton } from "../../components/bits";
import { emptyLicenceForm, type LicenceForm, licenceProblems, toLicenceIn } from "../../helpers/licence";
import { useChange } from "../../stepUp";
import { useRefreshOperator } from "../billing/invoiceDialogs";
import { UnitPicker } from "../plans/UnitPicker";

/** Issue and sign a licence. When it is made, the same box shows the signed file to download or copy. */
export function IssueLicenceDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation("operator");
  const refresh = useRefreshOperator();
  const plans = usePlans();
  const editions = useEditions();
  const [f, setF] = useState<LicenceForm>(emptyLicenceForm());
  const [showErrors, setShowErrors] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [issued, setIssued] = useState<Schemas["LicenceIssued"] | null>(null);
  const errors = licenceProblems(f);
  const patch = (p: Partial<LicenceForm>) => { setF((v) => ({ ...v, ...p })); setProblem(null); };
  const err = (key: string) => (showErrors && errors[key] ? t(`licences.errors.${errors[key]}`) : null);

  const issue = useChange(() => opUnwrap(opApi.POST("/api/v1/operator/licences", { body: toLicenceIn(f) })), {
    onSuccess: (licence) => { setIssued(licence); toast(t("licences.issued", { number: licence.licence_no }), "ok"); refresh(); },
    onError: (error) => setProblem(error.message),
  });
  const submit = () => {
    if (issue.isPending) return;
    if (Object.keys(errors).length > 0) { setShowErrors(true); return; }
    setProblem(null);
    issue.mutate(undefined);
  };

  if (issued) {
    const filename = `${issued.licence_no}.ziira-licence`;
    return (
      <Modal open onClose={onClose} title={t("licences.issuedTitle", { number: issued.licence_no })} size="md"
        footer={<><Button variant="secondary" onClick={() => saveText(issued.token, filename)}><Download className="h-4 w-4" /> {t("licences.downloadFile")}</Button><Button onClick={onClose}>{t("done")}</Button></>}>
        <div className="space-y-3 text-sm">
          <Alert tone="ok">{t("licences.issuedHint", { customer: issued.customer })}</Alert>
          <Field label={t("licences.file")} hint={filename}><Textarea readOnly value={issued.token} rows={6} className="break-all font-mono text-xs" onFocus={(e) => e.currentTarget.select()} /></Field>
          <CopyButton text={issued.token} label={t("licences.copyFile")} />
        </div>
      </Modal>
    );
  }

  return (
    <Modal open onClose={onClose} title={t("licences.issueTitle")} size="lg"
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="licence-form" loading={issue.isPending}>{t("licences.issueAndSign")}</Button></>}>
      <form id="licence-form" className="space-y-4" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Alert tone="info">{t("licences.keyNote")}</Alert>
        <FormGrid>
          <Field label={t("licences.customer")} error={err("customer")} required><Input value={f.customer} onChange={(e) => patch({ customer: e.target.value })} maxLength={160} autoFocus /></Field>
          <Field label={t("licences.email")} error={err("contact_email")}><Input type="email" value={f.contact_email} onChange={(e) => patch({ contact_email: e.target.value })} maxLength={200} /></Field>
        </FormGrid>

        <Field label={t("licences.basis")} hint={t(`licences.basisHints.${f.basis}`)}>
          <Select value={f.basis} onChange={(e) => patch({ basis: e.target.value as LicenceForm["basis"] })}>
            <option value="plan">{t("licences.bases.plan")}</option>
            <option value="units">{t("licences.bases.units")}</option>
          </Select>
        </Field>
        {f.basis === "plan" ? (
          <Field label={t("licences.planField")} error={err("plan_code")} required>
            <Select value={f.plan_code} onChange={(e) => patch({ plan_code: e.target.value })}>
              <option value="">{t("common.choosePlan")}</option>
              {(plans.data ?? []).map((p) => <option key={p.code} value={p.code}>{p.name} ({p.code})</option>)}
            </Select>
          </Field>
        ) : (
          <div className="space-y-3">
            <Field label={t("plans.editor.edition")}>
              <Select value={f.edition} onChange={(e) => patch({ edition: e.target.value })}>
                <option value="">{t("plans.editor.noEdition")}</option>
                {(editions.data ?? []).map((e) => <option key={e.id} value={e.id}>{e.title}</option>)}
              </Select>
            </Field>
            <UnitPicker label={t("plans.editor.units")} selected={f.units} onChange={(units) => patch({ units })} />
            {err("units") && <p role="alert" className="text-xs text-bad">{err("units")}</p>}
          </div>
        )}

        <fieldset>
          <legend className="text-sm font-medium">{t("licences.limits")}</legend>
          <p className="mb-2 text-xs text-muted">{t("licences.limitsHint")}</p>
          <FormGrid cols={3}>
            {(["max_users", "max_branches", "max_companies"] as const).map((k) => (
              <Field key={k} label={t(`plans.editor.${k}`)} error={err(k)}><NumberInput value={f[k]} placeholder={t("plans.unlimited")} onChange={(v) => patch({ [k]: v })} /></Field>
            ))}
          </FormGrid>
        </fieldset>

        <FormGrid>
          <div className="space-y-2">
            <Field label={t("licences.validUntil")} error={err("valid_until")}><Input type="date" value={f.valid_until} disabled={f.perpetual} onChange={(e) => patch({ valid_until: e.target.value })} /></Field>
            <Checkbox label={t("licences.perpetual")} checked={f.perpetual} onChange={(e) => patch({ perpetual: e.target.checked })} />
          </div>
          <Field label={t("licences.updateUntil")} hint={t("licences.updateUntilHint")}><Input type="date" value={f.update_until} onChange={(e) => patch({ update_until: e.target.value })} /></Field>
          <Field label={t("licences.grace")} hint={t("licences.graceHint")} error={err("grace_days")}><NumberInput value={f.grace_days} onChange={(v) => patch({ grace_days: v })} /></Field>
          <Field label={t("licences.instanceField")} hint={t("licences.instanceHint")} error={err("instance_id")}><Input value={f.instance_id} onChange={(e) => patch({ instance_id: e.target.value })} maxLength={64} className="font-mono" /></Field>
        </FormGrid>
        <Field label={t("licences.notes")}><Textarea value={f.notes} onChange={(e) => patch({ notes: e.target.value })} rows={2} maxLength={1000} /></Field>
        {problem && <Alert tone="bad">{problem}</Alert>}
      </form>
    </Modal>
  );
}
