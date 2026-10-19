import { Plus, X } from "lucide-react";

import { Button, Field, IconButton, Input, Select, useTranslation } from "@/sdk";

import { useTemplates } from "../hooks";
import type { ReceiveForm } from "../receive";

/** Optional checklist: copy a template's lines, then change them for this job. */
export function ReceiveChecklist({ companyId, form, update }: { companyId: string; form: ReceiveForm; update: (patch: Partial<ReceiveForm>) => void }) {
  const { t } = useTranslation("jobs");
  const templates = useTemplates(companyId, true);
  const lines = form.checklist;
  if (!templates.data?.length && lines.length === 0) return null;
  return (
    <div className="space-y-3">
      {!!templates.data?.length && (
        <Field label={t("receive.template")}>
          <Select className="h-11" value="" onChange={(e) => { const found = templates.data?.find((x) => x.id === e.target.value); if (found) update({ checklist: [...found.items] }); }}>
            <option value="">{lines.length > 0 ? t("receive.templateReplace") : t("receive.templatePick")}</option>
            {templates.data.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
          </Select>
        </Field>
      )}
      {lines.map((line, i) => (
        <div key={i} className="flex items-center gap-2">
          <Input aria-label={t("receive.checkLine")} className="h-11" maxLength={120} value={line} onChange={(e) => update({ checklist: lines.map((l, at) => (at === i ? e.target.value : l)) })} />
          <IconButton label={t("common.remove")} onClick={() => update({ checklist: lines.filter((_, at) => at !== i) })}><X className="h-4 w-4" /></IconButton>
        </div>
      ))}
      <Button variant="ghost" size="sm" onClick={() => update({ checklist: [...lines, ""] })}><Plus className="h-4 w-4" />{t("receive.addCheckLine")}</Button>
    </div>
  );
}
