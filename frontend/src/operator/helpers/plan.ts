/** The plan editor's form (all text), what is wrong with it, and the request the API takes. The server checks again. */
import { INTERVALS, type Interval } from "./format";

export const EXTRA_LIMITS = ["storage_mb", "documents_per_month", "api_requests_per_day"] as const;
export const PLAN_CODE = /^[a-z0-9][a-z0-9_-]{1,39}$/;

export interface PlanFormValues {
  code: string;
  name: string;
  description: string;
  edition: string;
  units: string[];
  addon_units: string[];
  max_users: string;
  max_branches: string;
  max_companies: string;
  limits: Record<string, string>;
  highlights: string;
  trial_days: string;
  intervals: Interval[];
  sort_order: string;
  is_public: boolean;
  status: "active" | "retired";
}

export const emptyPlanForm = (): PlanFormValues => ({
  code: "", name: "", description: "", edition: "", units: [], addon_units: [], max_users: "", max_branches: "", max_companies: "",
  limits: {}, highlights: "", trial_days: "0", intervals: ["month", "year"], sort_order: "100", is_public: false, status: "active",
});

interface PlanLike {
  code: string; name: string; description: string; edition: string | null; units: string[]; addon_units: string[];
  max_users: number | null; max_branches: number | null; max_companies: number | null; limits: Record<string, unknown>;
  highlights: string[]; trial_days: number; intervals: string[]; sort_order: number; is_public: boolean; status: string;
}

const text = (n: number | null | undefined): string => (n === null || n === undefined ? "" : String(n));

export function planToForm(plan: PlanLike): PlanFormValues {
  return {
    code: plan.code, name: plan.name, description: plan.description, edition: plan.edition ?? "", units: [...plan.units], addon_units: [...plan.addon_units],
    max_users: text(plan.max_users), max_branches: text(plan.max_branches), max_companies: text(plan.max_companies),
    limits: Object.fromEntries(Object.entries(plan.limits ?? {}).filter(([, v]) => v !== null && v !== undefined).map(([k, v]) => [k, String(v)])),
    highlights: plan.highlights.join("\n"), trial_days: String(plan.trial_days),
    intervals: plan.intervals.filter((i): i is Interval => (INTERVALS as readonly string[]).includes(i)),
    sort_order: String(plan.sort_order), is_public: plan.is_public, status: plan.status === "retired" ? "retired" : "active",
  };
}

/** A whole number in the range, or null when the box is empty (empty = unlimited); NaN for a bad entry. */
function wholeNumber(value: string): number | null {
  const clean = value.trim();
  if (clean === "") return null;
  return /^\d+$/.test(clean) ? Number(clean) : Number.NaN;
}

export const highlightLines = (value: string): string[] => value.split("\n").map((s) => s.trim()).filter(Boolean);

/** Field -> a key under "plans.editor.errors". Empty when the form can be sent. */
export function planProblems(v: PlanFormValues, creating: boolean): Record<string, string> {
  const errors: Record<string, string> = {};
  if (creating && !PLAN_CODE.test(v.code.trim())) errors.code = "code";
  if (!v.name.trim()) errors.name = "nameRequired";
  else if (v.name.trim().length > 80) errors.name = "nameLong";
  for (const key of ["max_users", "max_branches", "max_companies"] as const) {
    const n = wholeNumber(v[key]);
    if (n !== null && (Number.isNaN(n) || n < 1)) errors[key] = "limit";
  }
  for (const key of EXTRA_LIMITS) {
    const n = wholeNumber(v.limits[key] ?? "");
    if (n !== null && (Number.isNaN(n) || n < 0)) errors[key] = "limit";
  }
  const trial = wholeNumber(v.trial_days);
  if (trial === null || Number.isNaN(trial) || trial > 365) errors.trial_days = "trialDays";
  const order = wholeNumber(v.sort_order);
  if (order === null || Number.isNaN(order) || order > 100000) errors.sort_order = "sortOrder";
  if (v.intervals.length === 0) errors.intervals = "intervals";
  if (highlightLines(v.highlights).length > 12) errors.highlights = "highlights";
  if (v.units.length === 0 && !v.edition) errors.units = "units";
  return errors;
}

function common(v: PlanFormValues) {
  const limits: Record<string, number> = {};
  for (const key of EXTRA_LIMITS) {
    const n = wholeNumber(v.limits[key] ?? "");
    if (n !== null) limits[key] = n;
  }
  return {
    name: v.name.trim(),
    description: v.description.trim(),
    edition: v.edition.trim() || null,
    units: v.units,
    addon_units: v.addon_units,
    max_users: wholeNumber(v.max_users),
    max_branches: wholeNumber(v.max_branches),
    max_companies: wholeNumber(v.max_companies),
    limits,
    highlights: highlightLines(v.highlights),
    trial_days: wholeNumber(v.trial_days) ?? 0,
    intervals: v.intervals,
    sort_order: wholeNumber(v.sort_order) ?? 100,
    is_public: v.is_public,
  };
}

/** A new plan. */
export const toPlanIn = (v: PlanFormValues) => ({ code: v.code.trim(), ...common(v) });

/** A change to a plan: everything the form shows (an emptied limit means unlimited), and its active/retired state. */
export const toPlanPatch = (v: PlanFormValues) => ({ ...common(v), status: v.status });
