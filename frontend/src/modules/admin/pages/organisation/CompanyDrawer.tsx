import { type FormEvent, useState } from "react";

import {
  api, ApiError, Button, Drawer, ErrorText, Field, FormGrid, Input, orNull, Switch, toast, unwrap, useFormState, useMutation, useQueryClient, useTranslation, type Schemas,
} from "@/sdk";

type Company = Schemas["CompanySummary"];

/** Time zone names the browser knows, offered as suggestions while typing. */
const ZONES: string[] = (Intl as unknown as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf?.("timeZone") ?? [];

/** Add a company (with its first branch), or edit one. The currency is fixed once the company has postings. Mount it only while open. */
export function CompanyDrawer({ company, onClose }: { company: Company | null; onClose: () => void }) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const f = useFormState({
    name: company?.name ?? "", currency: company?.currency ?? "", country: company?.country ?? "", tax_id: company?.tax_id ?? "",
    timezone: company?.timezone ?? "", branch_code: "", branch_name: "",
  });
  const [vat, setVat] = useState(company?.vat_registered ?? false);
  const locked = !!company?.currency_locked;

  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => {
      const v = f.values;
      const common = { name: v.name.trim(), country: orNull(v.country), tax_id: orNull(v.tax_id), timezone: orNull(v.timezone), vat_registered: vat };
      if (company) {
        return unwrap(api.PATCH("/api/v1/companies/{company_id}", { params: { path: { company_id: company.id } }, body: { ...common, ...(locked ? {} : { currency: v.currency.trim() }) } }));
      }
      return unwrap(api.POST("/api/v1/companies", { body: { ...common, currency: v.currency.trim(), branch_code: orNull(v.branch_code), branch_name: orNull(v.branch_name) } }));
    },
    onSuccess: (c) => {
      void qc.invalidateQueries({ queryKey: ["organisation"] });
      void qc.invalidateQueries({ queryKey: ["companies"] });
      toast(t(company ? "org.companySaved" : "org.companyAdded", { name: c.name }), "ok");
      onClose();
    },
    onError: (e) => { f.fail(e); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  const needBranch = !company && (!!f.values.branch_code.trim() !== !!f.values.branch_name.trim());

  return (
    <Drawer open onClose={onClose} title={company ? t("org.editCompany") : t("org.addCompany")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="company-form" loading={save.isPending} disabled={needBranch}>{t("save")}</Button></>}>
      <form id="company-form" onSubmit={submit} className="space-y-4">
        <Field label={t("org.companyName")} required error={f.error("name")}><Input {...f.bind("name")} required autoFocus /></Field>
        <FormGrid>
          <Field label={t("org.currency")} required error={f.error("currency")} hint={locked ? t("org.currencyLocked") : t("org.currencyHint")}>
            <Input {...f.bind("currency")} required maxLength={3} disabled={locked} className="uppercase" />
          </Field>
          <Field label={t("org.country")} error={f.error("country")} hint={t("org.countryHint")}><Input {...f.bind("country")} maxLength={2} className="uppercase" /></Field>
        </FormGrid>
        <FormGrid>
          <Field label={t("org.taxId")} error={f.error("tax_id")}><Input {...f.bind("tax_id")} /></Field>
          <Field label={t("org.timezone")} error={f.error("timezone")} hint={t("org.timezoneHint")}>
            <Input {...f.bind("timezone")} list="org-zones" />
            <datalist id="org-zones">{ZONES.map((z) => <option key={z} value={z} />)}</datalist>
          </Field>
        </FormGrid>
        <Switch checked={vat} onChange={setVat} label={t("org.taxRegistered")} />
        {!company && (
          <fieldset className="space-y-3 rounded-xl bg-sunken p-4">
            <legend className="px-1 text-sm font-semibold">{t("org.firstBranch")}</legend>
            <p className="text-xs text-muted">{t("org.firstBranchHint")}</p>
            <FormGrid>
              <Field label={t("org.branchCode")} error={f.error("branch_code")}><Input {...f.bind("branch_code")} maxLength={10} className="uppercase" /></Field>
              <Field label={t("org.branchName")} error={f.error("branch_name")}><Input {...f.bind("branch_name")} /></Field>
            </FormGrid>
          </fieldset>
        )}
        <ErrorText>{save.error instanceof ApiError && Object.keys(save.error.fields).length === 0 ? save.error.message : null}</ErrorText>
      </form>
    </Drawer>
  );
}
