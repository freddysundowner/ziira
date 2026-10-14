import { Plus, X } from "lucide-react";

import { Button, Field, FormGrid, IconButton, Input, NumberInput, Select, useTranslation } from "@/sdk";

import { emptySide, type MethodKind, type SideForm } from "../lib/rules";

/** One side of a rule (what the employee pays, or what the employer pays): a method and its numbers. */
export function SideEditor({ who, value, onChange, currency }: { who: "employee" | "employer"; value: SideForm; onChange: (next: SideForm) => void; currency?: string }) {
  const { t } = useTranslation("people");
  const set = (patch: Partial<SideForm>) => onChange({ ...value, ...patch });
  const unit = currency ? ` (${currency})` : "";
  // A new band goes before the open-ended last one, which keeps its place at the end.
  const addBand = () => set({ bands: [...value.bands.slice(0, -1), { upTo: "", rate: "" }, value.bands.at(-1) ?? { upTo: "", rate: "" }] });
  const setBand = (i: number, patch: Partial<SideForm["bands"][number]>) => set({ bands: value.bands.map((b, j) => (j === i ? { ...b, ...patch } : b)) });

  return (
    <section className="space-y-3 rounded-xl border border-line p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{t(`rules.${who}Part`)}</h3>
        <Select aria-label={t("rules.method")} className="w-auto" value={value.method}
          onChange={(e) => onChange({ ...emptySide(e.target.value as MethodKind), bands: value.bands })}>
          <option value="none">{t("rules.methods.none")}</option>
          <option value="rate">{t("rules.methods.rate")}</option>
          <option value="bands">{t("rules.methods.bands")}</option>
          <option value="fixed">{t("rules.methods.fixed")}</option>
        </Select>
      </div>
      {value.method === "none" && <p className="text-xs text-muted">{t(`rules.${who}None`)}</p>}
      {value.method === "fixed" && (
        <Field label={`${t("rules.fixedAmount")}${unit}`} hint={t("rules.fixedHint")}><NumberInput value={value.amount} onChange={(v) => set({ amount: v })} /></Field>
      )}
      {value.method === "rate" && (
        <FormGrid>
          <Field label={t("rules.rate")} hint={t("rules.rateHint")}><NumberInput value={value.rate} onChange={(v) => set({ rate: v })} /></Field>
          <span className="hidden sm:block" />
          <Field label={`${t("rules.baseMinimum")}${unit}`} hint={t("rules.baseMinimumHint")}><NumberInput value={value.baseMinimum} onChange={(v) => set({ baseMinimum: v })} /></Field>
          <Field label={`${t("rules.baseMaximum")}${unit}`} hint={t("rules.baseMaximumHint")}><NumberInput value={value.baseMaximum} onChange={(v) => set({ baseMaximum: v })} /></Field>
          <Field label={`${t("rules.minimum")}${unit}`} hint={t("rules.minimumHint")}><NumberInput value={value.minimum} onChange={(v) => set({ minimum: v })} /></Field>
          <Field label={`${t("rules.maximum")}${unit}`} hint={t("rules.maximumHint")}><NumberInput value={value.maximum} onChange={(v) => set({ maximum: v })} /></Field>
        </FormGrid>
      )}
      {value.method === "bands" && (
        <div className="space-y-3">
          <p className="text-xs text-muted">{t("rules.bandsHint")}</p>
          <div className="space-y-2">
            {value.bands.map((b, i) => {
              const last = i === value.bands.length - 1;
              return (
                <div key={i} className="flex items-end gap-2">
                  <Field label={i === 0 ? `${t("rules.bandUpTo")}${unit}` : t("rules.bandUpTo")} className="flex-1">
                    {last ? <Input disabled value={t("rules.andAbove")} readOnly /> : <NumberInput value={b.upTo} onChange={(v) => setBand(i, { upTo: v })} aria-label={t("rules.bandUpTo")} />}
                  </Field>
                  <Field label={t("rules.bandRate")} className="w-28"><NumberInput value={b.rate} onChange={(v) => setBand(i, { rate: v })} aria-label={t("rules.bandRate")} /></Field>
                  <IconButton label={t("remove")} disabled={value.bands.length < 2} onClick={() => set({ bands: value.bands.filter((_, j) => j !== i) })}><X className="h-4 w-4" /></IconButton>
                </div>
              );
            })}
          </div>
          <Button variant="secondary" size="sm" onClick={addBand}>
            <Plus className="h-3.5 w-3.5" />{t("rules.addBand")}
          </Button>
          <Field label={`${t("rules.credit")}${unit}`} hint={t("rules.creditHint")}><NumberInput value={value.credit} onChange={(v) => set({ credit: v })} /></Field>
        </div>
      )}
    </section>
  );
}
