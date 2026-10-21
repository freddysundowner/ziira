import { useState } from "react";

import { Button, Checkbox, Input, NumberInput, Switch, useTranslation } from "@/sdk";

import { isCurrency, type UnitSaleForm } from "../../helpers/planUnits";

/**
 * The small control under an unticked unit: offer it for sale or not, with its one-time price in each currency the
 * platform sells in. Nothing is saved here; the plan's Save bar writes it (the price is the same on every plan).
 */
export function SaleEditor({ name, sale, currencies, problem, onChange, onCurrency }: {
  name: string;
  sale: UnitSaleForm;
  currencies: string[];
  problem: "price" | "needsPrice" | null;
  onChange: (next: UnitSaleForm) => void;
  onCurrency: (code: string) => void;
}) {
  const { t } = useTranslation("operator");
  const [code, setCode] = useState("");
  const [bad, setBad] = useState(false);
  const add = () => {
    if (!isCurrency(code)) { setBad(true); return; }
    onCurrency(code.trim().toUpperCase());
    setCode("");
    setBad(false);
  };
  return (
    <div className="mt-2 space-y-3 rounded-lg border border-line bg-sunken/50 p-3">
      <div className="flex items-center gap-3">
        <Switch checked={sale.offered} onChange={(offered) => onChange({ ...sale, offered })} label={t("plans.editor.offerSwitch", { name })} />
        <span className="text-sm font-medium">{t("plans.editor.offer")}</span>
      </div>
      {sale.offered && (
        <div className="space-y-3">
          {currencies.length > 0 && (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {currencies.map((c) => (
                <label key={c} className="block text-sm">
                  <span className="mb-1 block text-xs text-muted">{t("plans.editor.priceIn", { currency: c })}</span>
                  <NumberInput value={sale.prices[c] ?? ""} inputMode="decimal" aria-label={`${name} ${c}`} onChange={(v) => onChange({ ...sale, prices: { ...sale.prices, [c]: v } })} />
                </label>
              ))}
            </div>
          )}
          {currencies.length === 0 && <p className="text-xs text-muted">{t("plans.editor.needsCurrency")}</p>}
          <div className="flex flex-wrap items-end gap-2">
            <label className="block text-sm">
              <span className="mb-1 block text-xs text-muted">{t("plans.editor.addCurrency")}</span>
              <Input value={code} maxLength={3} placeholder={t("plans.editor.currencyPlaceholder")} className="w-32 font-mono uppercase" aria-label={`${t("plans.editor.addCurrency")} (${name})`}
                onChange={(e) => { setCode(e.target.value.toUpperCase()); setBad(false); }} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }} />
            </label>
            <Button type="button" size="sm" variant="secondary" onClick={add}>{t("plans.editor.currencyAdd")}</Button>
            {bad && <p role="alert" className="text-xs text-bad">{t("plans.editor.currencyBad")}</p>}
          </div>
          <Checkbox label={t("plans.editor.taxIncl")} checked={sale.tax_inclusive} onChange={(e) => onChange({ ...sale, tax_inclusive: e.target.checked })} />
          <p className="text-xs text-muted">{t("plans.editor.sameForAll")}</p>
        </div>
      )}
      {problem && <p role="alert" className="text-xs text-bad">{t(problem === "price" ? "plans.editor.errors.salePrice" : "plans.editor.errors.saleNeeds")}</p>}
    </div>
  );
}
