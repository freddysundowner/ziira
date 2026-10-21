/** The plan editor's list of units: which are ticked, which only because another needs them, and what each unticked one costs. */

export interface UnitInfo {
  name: string;
  title: string;
  description: string;
  kind: string; // kernel | module | plugin
  requires: string[];
}

export type UnitGroup = "module" | "plugin";

/** The kernel is always on and is never listed; everything else is a module or a plugin/pack. */
export const sellableUnits = (units: readonly UnitInfo[]): UnitInfo[] => units.filter((u) => u.kind !== "kernel");

export const groupOf = (u: Pick<UnitInfo, "kind">): UnitGroup => (u.kind === "module" ? "module" : "plugin");

/** Everything a set of ticked units includes: themselves and, again and again, the units they require. */
export function withRequired(chosen: readonly string[], units: readonly UnitInfo[]): string[] {
  const byName = new Map(units.map((u) => [u.name, u]));
  const out = new Set<string>();
  const visit = (name: string) => {
    if (out.has(name)) return;
    out.add(name);
    for (const r of byName.get(name)?.requires ?? []) if (byName.has(r) && byName.get(r)?.kind !== "kernel") visit(r);   // the kernel is always on
  };
  chosen.forEach(visit);
  return [...out].sort();
}

/** The titles of the ticked units that need this one ("needed by Jobs"), empty when nothing does. */
export function neededBy(name: string, effective: readonly string[], units: readonly UnitInfo[]): string[] {
  const on = new Set(effective);
  return units.filter((u) => u.name !== name && on.has(u.name) && u.requires.includes(name)).map((u) => u.title);
}

/** What the form starts from: a plan's units minus those only there because another unit needs them. */
export function explicitUnits(effective: readonly string[], units: readonly UnitInfo[]): string[] {
  const on = new Set(effective);
  return effective.filter((n) => !units.some((u) => u.name !== n && on.has(u.name) && u.requires.includes(n)));
}

/** Tick a unit, or untick it. A unit another ticked unit needs stays included (`withRequired`), and the list shows it locked. */
export const toggleUnit = (chosen: readonly string[], name: string): string[] => (chosen.includes(name) ? chosen.filter((n) => n !== name) : [...chosen, name]);

/** Units matching the search words (title, technical name or description). */
export function searchUnits(units: readonly UnitInfo[], query: string): UnitInfo[] {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return units.filter((u) => words.every((w) => `${u.title} ${u.name} ${u.description}`.toLowerCase().includes(w)));
}

/** "9 included, 4 for sale". */
export function planCounts(effective: readonly string[], sales: Record<string, UnitSaleForm>, units: readonly UnitInfo[]): { included: number; forSale: number } {
  const on = new Set(effective);
  const forSale = units.filter((u) => !on.has(u.name) && isOffered(sales[u.name])).length;
  return { included: units.filter((u) => on.has(u.name)).length, forSale };
}

// ---------------------------------------------------------------- selling an unticked unit on its own

export interface UnitSaleForm {
  offered: boolean;
  prices: Record<string, string>; // currency -> amount as typed ("" = not sold in that currency)
  tax_inclusive: boolean;
}

export const emptySale = (): UnitSaleForm => ({ offered: false, prices: {}, tax_inclusive: false });

interface SaleLike {
  unit: string;
  offered: boolean;
  prices: Record<string, number | string>;
  tax_inclusive: boolean;
}

export function salesToForm(rows: readonly SaleLike[]): Record<string, UnitSaleForm> {
  return Object.fromEntries(rows.map((r) => [r.unit, { offered: r.offered, prices: Object.fromEntries(Object.entries(r.prices).map(([c, a]) => [c, String(a)])), tax_inclusive: r.tax_inclusive }]));
}

const AMOUNT = /^\d+(\.\d{1,2})?$/;
const livePrices = (s: UnitSaleForm | undefined): [string, string][] => Object.entries(s?.prices ?? {}).filter(([, a]) => a.trim() !== "");

/** True when the platform really sells it: switched on and priced somewhere. */
export const isOffered = (s: UnitSaleForm | undefined): boolean => !!s?.offered && livePrices(s).length > 0;

/** Problems with one sale: "price" (a bad amount), "needsPrice" (offered with no price). Empty when fine. */
export function saleProblem(s: UnitSaleForm | undefined): "price" | "needsPrice" | null {
  if (!s) return null;
  for (const [, amount] of livePrices(s)) if (!AMOUNT.test(amount.trim()) || Number(amount) <= 0) return "price";
  return s.offered && livePrices(s).length === 0 ? "needsPrice" : null;
}

/** The units whose sale setting is wrong, as unit -> problem. Ticked units are skipped: they are not sold. */
export function saleProblems(sales: Record<string, UnitSaleForm>, effective: readonly string[]): Record<string, "price" | "needsPrice"> {
  const on = new Set(effective);
  const out: Record<string, "price" | "needsPrice"> = {};
  for (const [unit, s] of Object.entries(sales)) {
    const p = on.has(unit) ? null : saleProblem(s);
    if (p) out[unit] = p;
  }
  return out;
}

const normal = (s: UnitSaleForm | undefined) => JSON.stringify({ o: !!s?.offered, t: !!s?.tax_inclusive, p: livePrices(s).map(([c, a]) => [c, Number(a)]).sort() });

/** Units whose sale setting differs from what is stored. */
export function changedSales(now: Record<string, UnitSaleForm>, before: Record<string, UnitSaleForm>): string[] {
  return Object.keys({ ...before, ...now }).filter((u) => normal(now[u]) !== normal(before[u]));
}

/** The request body of one unit's sale: a currency the person emptied is sent as null (withdrawn). */
export function toSaleIn(now: UnitSaleForm, before: UnitSaleForm | undefined) {
  const prices: Record<string, string | null> = {};
  for (const [c, a] of livePrices(now)) prices[c] = a.trim();
  for (const c of Object.keys(before?.prices ?? {})) if (!(c in prices) && (before?.prices[c] ?? "").trim() !== "") prices[c] = null;
  return { offered: now.offered, prices, tax_inclusive: now.tax_inclusive };
}

/** The currencies the sale prices can be typed in: the platform's, any already priced, and ones just added. */
export function saleCurrencies(platform: readonly string[], sales: Record<string, UnitSaleForm>, added: readonly string[]): string[] {
  const set = new Set<string>([...platform, ...added]);
  for (const s of Object.values(sales)) Object.keys(s.prices).forEach((c) => set.add(c));
  return [...set].sort();
}

export const isCurrency = (v: string): boolean => /^[A-Z]{3}$/.test(v.trim().toUpperCase());
