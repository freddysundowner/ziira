import { useState } from "react";

import { Button, Field, FormGrid, Select, useTranslation } from "@/sdk";

import { dateReadings, type Preview, splitFields } from "../uploadLogic";

const NONE = "__none";
export type Fix = { mapping: Record<string, string | null>; date_format: "iso" | "dmy" | "mdy"; decimal_separator: "." | "," };

/** The simple way to put it right: for each thing we need, which part of the file it is, shown with what is in it. */
export function GuidedFix({ preview, busy, onApply, onCancel }: { preview: Preview; busy: boolean; onApply: (fix: Fix) => void; onCancel: () => void }) {
  const { t, i18n } = useTranslation("connect");
  const { main, more } = splitFields(preview.fields);
  const [choice, setChoice] = useState<Record<string, string | null>>({});
  const [dates, setDates] = useState(preview.settings.date_format as Fix["date_format"]);
  const [decimal, setDecimal] = useState(preview.settings.decimal_separator as Fix["decimal_separator"]);
  const [showMore, setShowMore] = useState(false);
  const current = (name: string, guessed: string | null) => (name in choice ? choice[name] : guessed);
  const sample = preview.date_examples[0] ?? "";
  const reading = dateReadings(sample, i18n.language);

  const row = (f: (typeof main)[number]) => {
    const column = current(f.name, f.column);
    const examples = column ? (preview.sample.map((r) => r[column]).filter(Boolean).slice(0, 3)) : [];
    return (
      <Field key={f.name} label={t("upload.whichColumn", { label: f.label.toLowerCase() })} required={f.required}
        hint={examples.length ? t("upload.forExample", { value: examples.join("  ·  ") }) : undefined}>
        <Select value={column ?? NONE} onChange={(e) => setChoice((c) => ({ ...c, [f.name]: e.target.value === NONE ? null : e.target.value }))}>
          <option value={NONE}>{t("upload.noneOfThem")}</option>
          {preview.headers.map((h) => <option key={h} value={h}>{h}</option>)}
        </Select>
      </Field>
    );
  };
  const apply = () => onApply({
    mapping: Object.fromEntries(preview.fields.flatMap((f) => (f.name in choice ? [[f.name, choice[f.name]]] : f.column ? [[f.name, f.column]] : []))),
    date_format: dates, decimal_separator: decimal,
  });

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">{t("upload.fixHint")}</p>
      <FormGrid>{main.map(row)}</FormGrid>
      {more.length > 0 && (showMore ? <FormGrid>{more.map(row)}</FormGrid> : <Button variant="ghost" size="sm" onClick={() => setShowMore(true)}>{t("upload.showMore")}</Button>)}
      <FormGrid>
        <Field label={t("upload.dateQuestion")} hint={sample ? t("upload.forExample", { value: sample }) : undefined}>
          <Select value={dates} onChange={(e) => setDates(e.target.value as Fix["date_format"])}>
            <option value="iso">{t("upload.dateIso")}</option>
            <option value="dmy">{reading ? t("upload.dateMeans", { when: reading.dmy }) : t("upload.dateDmy")}</option>
            <option value="mdy">{reading ? t("upload.dateMeans", { when: reading.mdy }) : t("upload.dateMdy")}</option>
          </Select>
        </Field>
        <Field label={t("upload.amountQuestion")}>
          <Select value={decimal} onChange={(e) => setDecimal(e.target.value as Fix["decimal_separator"])}>
            <option value=".">{t("upload.amountPoint")}</option>
            <option value=",">{t("upload.amountComma")}</option>
          </Select>
        </Field>
      </FormGrid>
      <div className="flex flex-wrap gap-2">
        <Button loading={busy} onClick={apply}>{t("upload.checkAgain")}</Button>
        <Button variant="secondary" onClick={onCancel}>{t("upload.cancel")}</Button>
      </div>
    </div>
  );
}
