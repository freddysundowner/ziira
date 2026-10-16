import { Card, FormGrid, useTranslation } from "@/sdk";

import { localesOf, whatsappLink } from "./model";
import { EditorGate, LocalisedSetting, Note, SaveBar, TextSetting } from "./fields";
import { useSettingsEditor, type SettingsEditor } from "./useSettingsEditor";

/** Company names, contact details and the site's languages, with a live picture of how they will read in the site's footer and contact page. */
export default function CompanyTab() {
  const { t } = useTranslation("operator");
  const editor = useSettingsEditor("company");
  const locales = editor.ready ? parseLocales(String(editor.form.locales ?? "")) : localesOf(editor.query.data?.values);

  return (
    <EditorGate editor={editor}>
      <Note>{t("website.company.note")}</Note>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-4">
          <Card title={t("website.company.names")}>
            <FormGrid>
              <TextSetting editor={editor} name="company_legal_name" label={t("website.company.legalName")} hint={t("website.company.legalNameHint")} required />
              <TextSetting editor={editor} name="company_trading_name" label={t("website.company.tradingName")} />
              <TextSetting editor={editor} name="registration_number" label={t("website.company.registration")} hint={t("website.company.optionalDisplay")} />
              <TextSetting editor={editor} name="tax_id" label={t("website.company.taxId")} hint={t("website.company.optionalDisplay")} />
            </FormGrid>
            <div className="mt-4"><LocalisedSetting editor={editor} name="tagline" label={t("website.company.tagline")} locales={locales} /></div>
          </Card>
          <Card title={t("website.company.contact")}>
            <FormGrid>
              <TextSetting editor={editor} name="support_email" label={t("website.company.supportEmail")} type="email" required />
              <TextSetting editor={editor} name="sales_email" label={t("website.company.salesEmail")} type="email" />
              <TextSetting editor={editor} name="phones" label={t("website.company.phones")} hint={t("website.company.phonesHint")} multiline placeholder="+000 000 000 000" />
              <TextSetting editor={editor} name="whatsapp_number" label={t("website.company.whatsapp")} hint={t("website.company.whatsappHint")} placeholder="+000 000 000 000" />
              <TextSetting editor={editor} name="contact_form_target" label={t("website.company.formTarget")} hint={t("website.company.formTargetHint")} />
            </FormGrid>
            <div className="mt-4"><TextSetting editor={editor} name="postal_address" label={t("website.company.address")} multiline /></div>
          </Card>
          <Card title={t("website.company.links")}>
            <FormGrid>
              <TextSetting editor={editor} name="app_url" label={t("website.company.appUrl")} hint={t("website.company.appUrlHint")} placeholder="https://" />
              <TextSetting editor={editor} name="status_page_url" label={t("website.company.statusUrl")} placeholder="https://" />
              <TextSetting editor={editor} name="locales" label={t("website.company.locales")} hint={t("website.company.localesHint")} placeholder="en, sw" />
            </FormGrid>
          </Card>
        </div>
        <CompanyPreview editor={editor} />
      </div>
      <SaveBar editor={editor} />
    </EditorGate>
  );
}

const parseLocales = (text: string): string[] => {
  const list = text.split(/[,\s]+/).filter((l) => /^[a-z]{2,3}(-[A-Z]{2})?$/.test(l));
  return list.length ? list : localesOf(undefined);
};

function CompanyPreview({ editor }: { editor: SettingsEditor }) {
  const { t } = useTranslation("operator");
  const text = (key: string) => String(editor.form[key] ?? "").trim();
  const phones = text("phones").split(/\n|,/).map((p) => p.trim()).filter(Boolean);
  const wa = whatsappLink(text("whatsapp_number"));
  const name = text("company_trading_name") || text("company_legal_name");
  const empty = !name && !text("support_email") && phones.length === 0 && !text("postal_address");
  return (
    <aside aria-label={t("website.company.preview")} className="lg:sticky lg:top-20 lg:self-start">
      <Card title={t("website.company.preview")} description={t("website.company.previewHint")}>
        {empty ? <p className="text-sm text-muted">{t("website.company.previewEmpty")}</p> : (
          <div className="space-y-3 rounded-lg bg-sunken p-4 text-sm">
            <p className="font-semibold">{name || "-"}</p>
            {text("company_trading_name") && text("company_legal_name") && <p className="text-xs text-muted">{text("company_legal_name")}</p>}
            {text("postal_address") && <p className="whitespace-pre-line text-muted">{text("postal_address")}</p>}
            <ul className="space-y-1">
              {text("support_email") && <li>{text("support_email")}</li>}
              {text("sales_email") && <li>{text("sales_email")}</li>}
              {phones.map((p) => <li key={p} className="tnum">{p}</li>)}
              {wa && <li className="break-all text-xs text-muted">{wa}</li>}
            </ul>
            {(text("registration_number") || text("tax_id")) && (
              <p className="border-t border-line pt-2 text-xs text-muted">
                {[text("registration_number"), text("tax_id")].filter(Boolean).join(" / ")}
              </p>
            )}
          </div>
        )}
      </Card>
    </aside>
  );
}
