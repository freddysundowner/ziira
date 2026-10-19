import { Card, FormGrid, useTranslation } from "@/sdk";

import { EditorGate, LocalisedSetting, Note, SaveBar, SwitchSetting, TextSetting } from "./fields";
import { localesOf } from "./model";
import { useSettingsEditor } from "./useSettingsEditor";

/** The announcement banner above the site's header: text per language, an optional link, an optional window. */
export default function BannerTab() {
  const { t } = useTranslation("operator");
  const editor = useSettingsEditor("banner");
  const locales = localesOf(editor.query.data?.values);
  const text = (editor.form.banner_text ?? {}) as Record<string, string>;
  return (
    <EditorGate editor={editor}>
      <Note>{t("website.banner.note")}</Note>
      <div className="space-y-4">
        <Card title={t("website.banner.title")}>
          <div className="space-y-4">
            <SwitchSetting editor={editor} name="banner_active" label={t("website.banner.active")} hint={t("website.banner.activeHint")} />
            <LocalisedSetting editor={editor} name="banner_text" label={t("website.banner.text")} locales={locales} />
            <TextSetting editor={editor} name="banner_link" label={t("website.banner.link")} hint={t("website.banner.linkHint")} />
            <FormGrid>
              <TextSetting editor={editor} name="banner_starts_at" label={t("website.banner.starts")} type="datetime-local" />
              <TextSetting editor={editor} name="banner_ends_at" label={t("website.banner.ends")} type="datetime-local" />
            </FormGrid>
            <p className="text-xs text-muted">{t("website.banner.windowHint")}</p>
          </div>
        </Card>
        <Card title={t("website.banner.preview")}>
          <div className="space-y-2">
            {locales.map((locale) => (
              <div key={locale} className="rounded-lg bg-brand px-4 py-2 text-center text-sm text-brand-ink">
                <span className="mr-2 text-xs opacity-70">{locale.toUpperCase()}</span>{text[locale] || <span className="opacity-70">{t("website.banner.previewEmpty")}</span>}
              </div>
            ))}
          </div>
        </Card>
      </div>
      <SaveBar editor={editor} />
    </EditorGate>
  );
}
