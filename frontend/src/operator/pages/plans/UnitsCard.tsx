import { useState } from "react";

import { Badge, Button, Card, Checkbox, ErrorState, type Edition, Input, money, Select, Skeleton, useTranslation } from "@/sdk";

import { groupOf, isOffered, neededBy, planCounts, searchUnits, type UnitGroup, type UnitInfo, type UnitSaleForm, withRequired } from "../../helpers/planUnits";
import { SaleEditor } from "./SaleEditor";

interface Props {
  units: UnitInfo[] | undefined;
  loading: boolean;
  error: Error | null;
  onRetry: () => void;
  chosen: string[];
  missing: string[];
  sales: Record<string, UnitSaleForm>;
  currencies: string[];
  problems: Record<string, "price" | "needsPrice">;
  editions: readonly Edition[];
  disabled: boolean;
  onToggle: (name: string) => void;
  onSale: (name: string, next: UnitSaleForm) => void;
  onCurrency: (code: string) => void;
  onEdition: (edition: Edition) => void;
}

const GROUPS: { id: UnitGroup; label: string }[] = [{ id: "module", label: "groupModules" }, { id: "plugin", label: "groupPlugins" }];

/** ONE list of every module and plugin. A tick means "in this plan"; an unticked row says how it is sold on its own. */
export function UnitsCard(p: Props) {
  const { t } = useTranslation("operator");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const all = p.units ?? [];
  const effective = withRequired(p.chosen, all);
  const on = new Set(effective);
  const counts = planCounts(effective, p.sales, all);
  const shown = searchUnits(all, query);

  return (
    <Card title={t("plans.editor.included")} description={t("plans.editor.includedHint")}>
      {p.loading && <Skeleton className="h-40 w-full" />}
      {p.error && <ErrorState title={t("plans.editor.unitsFailed")} message={p.error.message} onRetry={p.onRetry} />}
      {p.units && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="w-full sm:w-72"><Input aria-label={t("plans.editor.searchUnits")} placeholder={t("plans.editor.searchUnits")} value={query} onChange={(e) => setQuery(e.target.value)} /></div>
            <p className="text-sm font-medium" role="status" aria-live="polite">{t("plans.editor.counts", { included: counts.included, forSale: counts.forSale })}</p>
          </div>
          {shown.length === 0 && <p className="text-sm text-muted">{t("plans.editor.noUnitMatch")}</p>}
          {GROUPS.map((g) => {
            const rows = shown.filter((u) => groupOf(u) === g.id);
            if (rows.length === 0) return null;
            return (
              <section key={g.id} aria-label={t(`plans.editor.${g.label}`)}>
                <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">{t(`plans.editor.${g.label}`)} <span className="font-normal">({rows.length})</span></h3>
                <ul className="divide-y divide-line rounded-lg border border-line">
                  {rows.map((u) => {
                    const needed = neededBy(u.name, effective, all);
                    const locked = needed.length > 0 && on.has(u.name);
                    return (
                      <li key={u.name} className="px-3 py-2.5" data-unit={u.name}>
                        <Checkbox checked={on.has(u.name)} disabled={p.disabled || locked} onChange={() => p.onToggle(u.name)} aria-label={`${t("plans.editor.inPlan")}: ${u.title}`} className="items-start"
                          label={<span className="min-w-0"><span className="font-medium">{u.title}</span> <span className="font-mono text-xs text-muted">{u.name}</span>{u.description && <span className="block text-xs font-normal text-muted">{u.description}</span>}</span>} />
                        <div className="ml-6 mt-1">
                          {on.has(u.name) ? (
                            <p className="text-xs text-ok">{locked ? t("plans.editor.neededBy", { names: needed.join(", ") }) : t("plans.editor.rowIncluded")}</p>
                          ) : (
                            <SellingLine unit={u} sale={p.sales[u.name]} open={open === u.name} disabled={p.disabled} onOpen={() => setOpen(open === u.name ? null : u.name)}
                              currencies={p.currencies} problem={p.problems[u.name] ?? null} onSale={(next) => p.onSale(u.name, next)} onCurrency={p.onCurrency} />
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </section>
            );
          })}
          {p.missing.length > 0 && (
            <section aria-label={t("plans.editor.groupMissing")}>
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">{t("plans.editor.groupMissing")}</h3>
              <ul className="rounded-lg border border-line">
                {p.missing.map((n) => (
                  <li key={n} className="px-3 py-2"><Checkbox checked disabled={p.disabled} onChange={() => p.onToggle(n)} label={<span><span className="font-mono text-xs">{n}</span> <span className="text-xs text-warn">{t("plans.editor.notFound")}</span></span>} /></li>
                ))}
              </ul>
            </section>
          )}
          <Advanced editions={p.editions} disabled={p.disabled} onEdition={p.onEdition} />
        </div>
      )}
    </Card>
  );
}

function SellingLine({ unit, sale, open, disabled, onOpen, currencies, problem, onSale, onCurrency }: {
  unit: UnitInfo; sale: UnitSaleForm | undefined; open: boolean; disabled: boolean; onOpen: () => void; currencies: string[];
  problem: "price" | "needsPrice" | null; onSale: (next: UnitSaleForm) => void; onCurrency: (code: string) => void;
}) {
  const { t } = useTranslation("operator");
  const form = sale ?? { offered: false, prices: {}, tax_inclusive: false };
  const offered = isOffered(sale);
  const priced = Object.entries(form.prices).filter(([, a]) => a.trim() !== "").map(([c, a]) => money(a, c)).join(" / ");
  return (
    <div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {offered ? <Badge tone="info">{t("plans.editor.soldFor", { price: priced })}</Badge> : <Badge>{t("plans.editor.notForSale")}</Badge>}
        {!disabled && <Button type="button" size="sm" variant="ghost" aria-expanded={open} onClick={onOpen}>{offered ? t("plans.editor.change") : t("plans.editor.offer")}</Button>}
      </div>
      {(open || problem) && !disabled && <SaleEditor name={unit.title} sale={form} currencies={currencies} problem={problem} onChange={onSale} onCurrency={onCurrency} />}
    </div>
  );
}

/** Rarely needed: tick the units of an edition in one go. */
function Advanced({ editions, disabled, onEdition }: { editions: readonly Edition[]; disabled: boolean; onEdition: (e: Edition) => void }) {
  const { t } = useTranslation("operator");
  const [id, setId] = useState("");
  const edition = editions.find((e) => e.id === id);
  return (
    <details className="rounded-lg border border-line px-3 py-2">
      <summary className="cursor-pointer text-sm font-medium">{t("plans.editor.advanced")}</summary>
      <div className="mt-3 space-y-2">
        <p className="text-sm font-medium">{t("plans.editor.startFrom")}</p>
        <p className="text-xs text-muted">{t("plans.editor.startFromHint")}</p>
        <div className="flex flex-wrap items-center gap-2">
          <div className="w-full sm:w-64">
            <Select aria-label={t("plans.editor.startFrom")} value={id} disabled={disabled} onChange={(e) => setId(e.target.value)}>
              <option value="">{t("plans.editor.startNone")}</option>
              {editions.map((e) => <option key={e.id} value={e.id}>{e.title}</option>)}
            </Select>
          </div>
          <Button type="button" size="sm" variant="secondary" disabled={disabled || !edition} onClick={() => edition && onEdition(edition)}>{t("plans.editor.startApply")}</Button>
        </div>
      </div>
    </details>
  );
}
