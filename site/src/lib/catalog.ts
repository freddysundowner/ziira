// The catalogue of Intelligence checks, actions and Ask Ziira tools, read from src/content/checks.catalog.json.
// That file is GENERATED from the real registry by `make site-catalog` (scripts/export_check_catalog.py): never edit it and never type a
// count by hand anywhere on the site; take it from `totals` or from the helpers here.
import raw from "../content/checks.catalog.json";

export interface CatalogLimit { name: string; label: string; default: string | number | boolean }
export interface CatalogCheck {
  code: string; area: string; group: string; title: string; description: string; plain: string; example: string;
  source: "ziira" | "connected"; unit: string; needs: string | null; severity: string; severity_label: string; closes_itself: boolean; limits: CatalogLimit[];
}
export interface CatalogGroup { key: string; title: string; lead: string; count: number; ziira: number; connected: number }
export interface CatalogAction {
  type: string; title: string; description: string; plain: string; example: string; kind: string; level: number;
  for_checks: { code: string; title: string }[]; permission: string; who_approves: string; automatic: boolean; rule_conditions: string[];
}
export interface CatalogTool { name: string; description: string; plain: string }
export interface Catalog {
  groups: CatalogGroup[];
  totals: { checks: number; ziira: number; connected: number; actions: number; automatic_actions: number; ask_tools: number; baselines: number; by_area: Record<string, number> };
  checks: CatalogCheck[];
  actions: CatalogAction[];
  ask_tools: CatalogTool[];
}

export const catalog = raw as unknown as Catalog;
export const totals = catalog.totals;

/** Plain names for the code-level areas (`by_area`). */
export const AREA_NAMES: Record<string, string> = {
  cash_sales: "Cash and sales", customers: "Customers and credit", suppliers: "Suppliers and purchasing", stock: "Stock", cash_planning: "Cash planning",
  books: "Books", people: "People and payroll", controls: "Controls", general: "General",
};

export const checkAnchor = (code: string) => `check-${code.replace(/[^a-z0-9]+/gi, "-")}`;
export const checkByCode = (code: string): CatalogCheck => {
  const c = catalog.checks.find((x) => x.code === code);
  if (!c) throw new Error(`Complete guide refers to a check that does not exist: ${code}`);
  return c;
};
export const checksIn = (group: string): CatalogCheck[] => catalog.checks.filter((c) => c.group === group);
/** A number with thousands separators for display ("2,000,000"). */
export const n = (v: number): string => v.toLocaleString("en-US");
