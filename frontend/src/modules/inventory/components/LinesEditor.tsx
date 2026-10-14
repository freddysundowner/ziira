import { Plus, Trash2 } from "lucide-react";

import { Button, IconButton, Input, NumberInput, Select, useTranslation } from "@/sdk";

import { newLine, type DraftLine } from "../logic";
import { ProductPicker } from "../lookups";

/** Rows of product + quantity for a stock document. `signed` adds Add/Remove, `opening` adds cost, batch and expiry. */
export function LinesEditor({ lines, onChange, signed, opening }: { lines: DraftLine[]; onChange: (lines: DraftLine[]) => void; signed?: boolean; opening?: boolean }) {
  const { t } = useTranslation("inventory");
  const update = (key: string, patch: Partial<DraftLine>) => onChange(lines.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  return (
    <div className="space-y-3">
      {lines.map((l, i) => (
        <div key={l.key} className="rounded-lg border border-line p-3">
          <div className="flex items-start gap-2">
            <div className="min-w-0 flex-1">
              <ProductPicker value={l.productId} label={l.productLabel} placeholder={t("pickProduct")} onChange={(id, name) => update(l.key, { productId: id, productLabel: name })} />
            </div>
            <IconButton label={t("removeLine")} onClick={() => onChange(lines.length > 1 ? lines.filter((x) => x.key !== l.key) : [newLine()])}><Trash2 className="h-4 w-4" /></IconButton>
          </div>
          <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {signed && (
              <Select aria-label={t("direction")} value={l.remove ? "out" : "in"} onChange={(e) => update(l.key, { remove: e.target.value === "out" })}>
                <option value="in">{t("addStock")}</option>
                <option value="out">{t("removeStock")}</option>
              </Select>
            )}
            <NumberInput aria-label={`${t("quantity")} ${i + 1}`} placeholder={t("quantity")} value={l.qty} onChange={(v) => update(l.key, { qty: v })} />
            {opening && <>
              <NumberInput aria-label={t("unitCost")} placeholder={t("unitCost")} value={l.unitCost} onChange={(v) => update(l.key, { unitCost: v })} />
              <Input aria-label={t("batchNo")} placeholder={t("batchNo")} value={l.batchNo} onChange={(e) => update(l.key, { batchNo: e.target.value })} />
              <Input type="date" aria-label={t("expiry")} value={l.expiry} onChange={(e) => update(l.key, { expiry: e.target.value })} />
            </>}
          </div>
        </div>
      ))}
      <Button variant="secondary" size="sm" onClick={() => onChange([...lines, newLine()])}><Plus className="h-4 w-4" />{t("addLine")}</Button>
    </div>
  );
}
