import { cx, Field, Input, useTranslation } from "@/sdk";

import { ITEM_KINDS } from "../lib";
import type { ReceiveForm, ReceiveProblem } from "../receive";
import { IdentifierRows } from "./IdentifierRows";
import { AssetPicker } from "./pickers";

/** Which item came in: one the shop already knows, or a new one with its identifying details. */
export function ReceiveItem({ form, update, problems }: { form: ReceiveForm; update: (patch: Partial<ReceiveForm>) => void; problems: ReceiveProblem[] }) {
  const { t } = useTranslation("jobs");
  return (
    <div className="space-y-4">
      <div role="group" aria-label={t("receive.item")} className="grid grid-cols-2 gap-1 rounded-xl bg-sunken p-1">
        {(["existing", "new"] as const).map((mode) => (
          <button key={mode} type="button" aria-pressed={form.itemMode === mode} onClick={() => update({ itemMode: mode })}
            className={cx("h-11 rounded-lg text-sm font-medium", form.itemMode === mode ? "bg-surface shadow-card" : "text-muted hover:text-ink")}>{t(`receive.itemMode.${mode}`)}</button>
        ))}
      </div>
      {form.itemMode === "existing" ? (
        <Field label={t("receive.findItem")} hint={t("receive.findItemHint")}><AssetPicker value={form.assetId} onChange={(id) => update({ assetId: id })} /></Field>
      ) : (
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t("receive.itemLabel")} hint={t("receive.itemLabelHint")} error={problems.includes("newLabel") ? t("receive.itemLabelNeeded") : null}>
              <Input className="h-11" maxLength={160} value={form.newLabel} onChange={(e) => update({ newLabel: e.target.value })} />
            </Field>
            <Field label={t("receive.itemKind")}>
              <Input className="h-11" list="jobs-item-kinds" maxLength={40} value={form.newKind} onChange={(e) => update({ newKind: e.target.value })} />
              <datalist id="jobs-item-kinds">{ITEM_KINDS.map((k) => <option key={k} value={t(`kinds.${k}`)} />)}</datalist>
            </Field>
          </div>
          <Field label={t("receive.identifiers")} hint={t("receive.identifiersHint")}><IdentifierRows large rows={form.newRows} onChange={(rows) => update({ newRows: rows })} /></Field>
        </div>
      )}
    </div>
  );
}
