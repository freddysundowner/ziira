import { Plus, Trash2 } from "lucide-react";

import { Alert, Button, Field, IconButton, money, NumberInput, Select, useCan, useTranslation } from "@/sdk";

import { ProductPicker } from "./hooks";
import { blankLine, type EditLine, estimateTotal, hasPriceChange } from "./lib";

const ROW = "grid gap-3 rounded-lg border border-line bg-sunken/40 p-3 md:items-end";

/**
 * The product rows of a quotation, order or invoice. Price and discount are shown only to people allowed to change
 * prices (the server refuses them otherwise); a blank price means the customer's list price.
 */
export function LinesEditor({ lines, onChange, reasonId, onReason, reasons, currency }: {
  lines: EditLine[]; onChange: (lines: EditLine[]) => void; reasonId: string; onReason: (id: string) => void;
  reasons: { id: string; label: string }[]; currency?: string;
}) {
  const { t } = useTranslation("pos");
  const canPrice = useCan("price.override");
  const update = (key: string, patch: Partial<EditLine>) => onChange(lines.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  const estimate = canPrice ? estimateTotal(lines) : null;
  const needsReason = canPrice && lines.some((l) => l.product_id && hasPriceChange(l));
  const cols = canPrice ? "md:grid-cols-[minmax(0,1fr)_6rem_8rem_7rem_2.25rem]" : "md:grid-cols-[minmax(0,1fr)_7rem_2.25rem]";

  return (
    <div className="space-y-3">
      {lines.map((l, i) => (
        <div key={l.key} className={`${ROW} ${cols}`}>
          <Field label={t("docs.lineProduct", { n: i + 1 })}><ProductPicker value={l.product_id} onChange={(v) => update(l.key, { product_id: v })} /></Field>
          <Field label={t("docs.quantity")}><NumberInput value={l.quantity} onChange={(v) => update(l.key, { quantity: v })} /></Field>
          {canPrice && <Field label={t("docs.unitPrice")}><NumberInput value={l.unit_price} placeholder={t("docs.listPriceShort")} onChange={(v) => update(l.key, { unit_price: v })} /></Field>}
          {canPrice && <Field label={t("docs.discount")}><NumberInput value={l.discount} placeholder="0" onChange={(v) => update(l.key, { discount: v })} /></Field>}
          <IconButton label={t("docs.removeLine")} className="justify-self-end" disabled={lines.length === 1} onClick={() => onChange(lines.filter((x) => x.key !== l.key))}><Trash2 className="h-4 w-4" /></IconButton>
        </div>
      ))}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button type="button" size="sm" variant="secondary" onClick={() => onChange([...lines, blankLine()])}><Plus className="h-4 w-4" />{t("docs.addLine")}</Button>
        {estimate !== null && <p className="text-sm text-muted">{t("docs.estimate")}: <span className="tnum font-medium text-ink">{money(estimate, currency)}</span></p>}
      </div>
      {needsReason && (
        <Field label={t("docs.priceReason")} required hint={t("docs.priceReasonHint")}>
          <Select value={reasonId} onChange={(e) => onReason(e.target.value)}>
            <option value="">{t("choose")}</option>
            {reasons.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
          </Select>
        </Field>
      )}
      <Alert tone="info">{t(canPrice ? "docs.linesHint" : "docs.linesHintNoPrice")}</Alert>
    </div>
  );
}
