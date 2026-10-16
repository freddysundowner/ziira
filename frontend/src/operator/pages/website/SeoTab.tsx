import { Alert, Card, FormGrid, useTranslation } from "@/sdk";

import { useAssets } from "./api";
import { AssetSetting, EditorGate, LocalisedSetting, Note, SaveBar, SwitchSetting, TextSetting } from "./fields";
import { localesOf, SEO_LIMITS } from "./model";
import { useSettingsEditor } from "./useSettingsEditor";

/** Defaults for search results and sharing, the logo and icon, and the (optional, off by default) analytics. */
export default function SeoTab() {
  const { t } = useTranslation("operator");
  const editor = useSettingsEditor("seo");
  const assets = useAssets();
  const locales = localesOf(editor.query.data?.values);
  const analyticsOn = editor.form.analytics_enabled === true;
  const description = (editor.form.seo_description ?? {}) as Record<string, string>;
  const tooLong = Object.values(description).some((d) => d.length > SEO_LIMITS.description);

  return (
    <EditorGate editor={editor}>
      <Note>{t("website.seo.note")}</Note>
      <div className="space-y-4">
        <Card title={t("website.seo.search")}>
          <div className="space-y-4">
            <LocalisedSetting editor={editor} name="seo_title_template" label={t("website.seo.titleTemplate")} hint={t("website.seo.titleTemplateHint")} locales={locales} />
            <LocalisedSetting editor={editor} name="seo_description" label={t("website.seo.description")} hint={t("website.seo.descriptionHint", { count: SEO_LIMITS.description })} locales={locales} multiline />
            {tooLong && <Alert tone="warn">{t("website.seo.tooLong", { count: SEO_LIMITS.description })}</Alert>}
          </div>
        </Card>
        <Card title={t("website.seo.brand")} description={t("website.seo.brandHint")}>
          {assets.isError ? <Alert tone="bad">{assets.error.message}</Alert> : (
            <FormGrid cols={3}>
              <AssetSetting editor={editor} name="logo" label={t("website.seo.logo")} assets={assets.data ?? []} />
              <AssetSetting editor={editor} name="favicon" label={t("website.seo.favicon")} assets={assets.data ?? []} />
              <AssetSetting editor={editor} name="og_image" label={t("website.seo.ogImage")} hint={t("website.seo.ogImageHint")} assets={assets.data ?? []} />
            </FormGrid>
          )}
        </Card>
        <Card title={t("website.seo.analytics")} description={t("website.seo.analyticsHint")}>
          <div className="space-y-4">
            <SwitchSetting editor={editor} name="analytics_enabled" label={t("website.seo.analyticsOn")} hint={t("website.seo.analyticsOnHint")} />
            {analyticsOn && (
              <>
                <TextSetting editor={editor} name="analytics_id" label={t("website.seo.analyticsId")} />
                <LocalisedSetting editor={editor} name="cookie_notice_text" label={t("website.seo.cookieNotice")} hint={t("website.seo.cookieNoticeHint")} locales={locales} multiline />
              </>
            )}
          </div>
        </Card>
      </div>
      <SaveBar editor={editor} />
    </EditorGate>
  );
}
