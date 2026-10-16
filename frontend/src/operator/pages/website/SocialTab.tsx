import { Card, FormGrid, useTranslation } from "@/sdk";

import { EditorGate, Note, SaveBar, TextSetting } from "./fields";
import { socialUrl, TAB_KEYS } from "./model";
import { useSettingsEditor } from "./useSettingsEditor";

const NETWORKS = TAB_KEYS.social.map((key) => ({ key, name: key.replace("social_", "") }));

/** Social profiles: a handle or a full address for each; empty ones are not shown on the site. */
export default function SocialTab() {
  const { t } = useTranslation("operator");
  const editor = useSettingsEditor("social");
  return (
    <EditorGate editor={editor}>
      <Note>{t("website.social.note")}</Note>
      <Card title={t("website.social.title")}>
        <FormGrid>
          {NETWORKS.map(({ key, name }) => {
            const url = socialUrl(key, String(editor.form[key] ?? ""));
            return (
              <div key={key}>
                <TextSetting editor={editor} name={key} label={t(`website.social.${name}`)} placeholder={name === "linkedin" ? "company-name" : "@handle"} />
                {url && <p className="mt-1 break-all text-xs text-muted">{url}</p>}
              </div>
            );
          })}
        </FormGrid>
      </Card>
      <SaveBar editor={editor} />
    </EditorGate>
  );
}
