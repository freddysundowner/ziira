/**
 * The statutory rule editor's model. A rule is data the business enters (the API stores it as a JSON definition), so
 * nothing here knows a country. People type rates as percentages; the API stores fractions as strings ("0.075"), moved
 * by shifting the decimal point in the text so no value passes through a float.
 */
import type { Rule } from "./types";

export type MethodKind = "none" | "rate" | "bands" | "fixed";
export const KINDS = ["tax", "contribution", "levy", "other"] as const;
export const BASES = ["gross", "basic", "taxable"] as const;
export const APPLIES = ["all", "resident", "non_resident"] as const;

export interface BandForm { upTo: string; rate: string }

/** One side (the employee's part, or the employer's) as the form holds it. Rates are percentages. */
export interface SideForm {
  method: MethodKind;
  rate: string;
  baseMinimum: string;
  baseMaximum: string;
  minimum: string;
  maximum: string;
  amount: string;
  credit: string;
  bands: BandForm[];
}

export interface RuleForm {
  code: string;
  name: string;
  kind: (typeof KINDS)[number];
  order: string;
  base: (typeof BASES)[number];
  appliesTo: (typeof APPLIES)[number];
  reducesTaxable: boolean;
  employee: SideForm;
  employer: SideForm;
  effectiveFrom: string;
  effectiveTo: string;
  sourceReference: string;
  payableAccountId: string;
}

export const emptySide = (method: MethodKind = "none"): SideForm => ({
  method, rate: "", baseMinimum: "", baseMaximum: "", minimum: "", maximum: "", amount: "", credit: "", bands: [{ upTo: "", rate: "" }],
});

export const emptyRule = (effectiveFrom: string): RuleForm => ({
  code: "", name: "", kind: "tax", order: "100", base: "gross", appliesTo: "all", reducesTaxable: false,
  employee: emptySide("rate"), employer: emptySide(), effectiveFrom, effectiveTo: "", sourceReference: "", payableAccountId: "",
});

/** Move the decimal point of a plain decimal string ("7.5") by `places` (positive: right). Returns "" for an empty or invalid text. */
export function shiftDecimal(value: string, places: number): string {
  const text = value.trim();
  if (!/^\d*\.?\d*$/.test(text) || text === "" || text === ".") return "";
  const [whole = "", fraction = ""] = text.split(".");
  let digits = whole + fraction;
  let point = whole.length + places;
  if (point <= 0) { digits = "0".repeat(1 - point) + digits; point = 1; }
  if (point > digits.length) digits += "0".repeat(point - digits.length);
  const integer = digits.slice(0, point).replace(/^0+(?=\d)/, "");
  const decimals = digits.slice(point).replace(/0+$/, "");
  return decimals ? `${integer}.${decimals}` : integer;
}

export const percentToRate = (percent: string): string => shiftDecimal(percent, -2);
export const rateToPercent = (rate: string): string => shiftDecimal(rate, 2);

const filled = (v: string) => v.trim() !== "";

function sideToDefinition(side: SideForm): Record<string, unknown> | null {
  if (side.method === "none") return null;
  if (side.method === "fixed") return { method: "fixed", amount: side.amount.trim() };
  if (side.method === "rate") {
    const out: Record<string, unknown> = { method: "rate", rate: percentToRate(side.rate) };
    if (filled(side.baseMinimum)) out.base_minimum = side.baseMinimum.trim();
    if (filled(side.baseMaximum)) out.base_maximum = side.baseMaximum.trim();
    if (filled(side.minimum)) out.minimum = side.minimum.trim();
    if (filled(side.maximum)) out.maximum = side.maximum.trim();
    return out;
  }
  return {
    method: "bands",
    credit: filled(side.credit) ? side.credit.trim() : "0",
    bands: side.bands.map((b, i) => ({ up_to: i === side.bands.length - 1 ? null : b.upTo.trim(), rate: percentToRate(b.rate) })),
  };
}

/** The `definition` the API stores. */
export function buildDefinition(form: RuleForm): Record<string, unknown> {
  return {
    name: form.name.trim(), kind: form.kind, order: Number(form.order || "100"), base: form.base, applies_to: form.appliesTo,
    reduces_taxable: form.reducesTaxable && form.employee.method !== "none",
    employee: sideToDefinition(form.employee), employer: sideToDefinition(form.employer),
  };
}

type Raw = Record<string, unknown> | null | undefined;
const text = (v: unknown): string => (v === null || v === undefined ? "" : String(v));

function sideFromDefinition(raw: Raw): SideForm {
  if (!raw || typeof raw !== "object") return emptySide();
  const method = raw.method;
  if (method === "fixed") return { ...emptySide("fixed"), amount: text(raw.amount) };
  if (method === "rate") {
    return { ...emptySide("rate"), rate: rateToPercent(text(raw.rate)), baseMinimum: text(raw.base_minimum), baseMaximum: text(raw.base_maximum), minimum: text(raw.minimum), maximum: text(raw.maximum) };
  }
  if (method === "bands") {
    const bands = Array.isArray(raw.bands) ? (raw.bands as Record<string, unknown>[]) : [];
    return { ...emptySide("bands"), credit: text(raw.credit) === "0" ? "" : text(raw.credit), bands: bands.length ? bands.map((b) => ({ upTo: text(b.up_to), rate: rateToPercent(text(b.rate)) })) : [{ upTo: "", rate: "" }] };
  }
  return emptySide();
}

const pick = <T extends string>(allowed: readonly T[], value: unknown, fallback: T): T => (allowed.includes(value as T) ? (value as T) : fallback);

/** A stored rule back into the editor (to look at it, or to start a new version from it). */
export function ruleToForm(rule: Rule): RuleForm {
  const d = rule.definition as Record<string, unknown>;
  return {
    code: rule.code, name: text(d.name), kind: pick(KINDS, d.kind, "other"), order: text(d.order ?? 100), base: pick(BASES, d.base, "gross"),
    appliesTo: pick(APPLIES, d.applies_to, "all"), reducesTaxable: d.reduces_taxable === true,
    employee: sideFromDefinition(d.employee as Raw), employer: sideFromDefinition(d.employer as Raw),
    effectiveFrom: rule.effective_from, effectiveTo: rule.effective_to ?? "", sourceReference: rule.source_reference, payableAccountId: rule.payable_account_id ?? "",
  };
}

/** What the screen can check before asking the server (which checks again). Each result is a translation key under "rules.problem". */
export function problems(form: RuleForm): string[] {
  const out: string[] = [];
  if (!/^[A-Z][A-Z0-9_]{0,19}$/.test(form.code.trim().toUpperCase())) out.push("code");
  if (!form.name.trim()) out.push("name");
  if (form.employee.method === "none" && form.employer.method === "none") out.push("noParts");
  if (form.sourceReference.trim().length < 3) out.push("source");
  if (!form.effectiveFrom) out.push("from");
  if (form.effectiveTo && form.effectiveTo < form.effectiveFrom) out.push("range");
  if (form.reducesTaxable && form.base === "taxable") out.push("reduceTaxable");
  for (const side of [form.employee, form.employer]) {
    if (side.method === "rate" && (!filled(side.rate) || Number(side.rate) > 100)) out.push("rate");
    if (side.method === "fixed" && !filled(side.amount)) out.push("amount");
    if (side.method === "bands") {
      let previous = 0;
      side.bands.forEach((b, i) => {
        if (!filled(b.rate) || Number(b.rate) > 100) out.push("bandRate");
        if (i < side.bands.length - 1) {
          if (!filled(b.upTo) || Number(b.upTo) <= previous) out.push("bandOrder");
          previous = Number(b.upTo);
        }
      });
    }
  }
  return [...new Set(out)];
}

export interface BandRange { from: string; to: string | null; rate: string }

/** The bands as ranges ("0 to 24000 at 10%"), for the preview table. */
export function bandRanges(bands: BandForm[]): BandRange[] {
  let from = "0";
  return bands.map((b, i) => {
    const last = i === bands.length - 1;
    const range = { from, to: last ? null : b.upTo.trim() || "…", rate: b.rate.trim() || "…" };
    from = b.upTo.trim() || "…";
    return range;
  });
}

/**
 * An illustration of what one side takes from a base amount, for the editor's "try it" box. It mirrors the server's method
 * so a person can check a rule against the official notice; payroll itself always uses the server's calculation.
 */
export function illustrate(side: SideForm, base: number): number {
  if (side.method === "none" || !Number.isFinite(base)) return 0;
  if (side.method === "fixed") return base > 0 ? Number(side.amount || 0) : 0;
  if (base <= 0) return 0;
  if (side.method === "rate") {
    if (filled(side.baseMinimum) && base < Number(side.baseMinimum)) return 0;
    const charged = filled(side.baseMaximum) ? Math.min(base, Number(side.baseMaximum)) : base;
    let amount = Math.round(charged * Number(side.rate || 0)) / 100;
    if (filled(side.minimum)) amount = Math.max(amount, Number(side.minimum));
    if (filled(side.maximum)) amount = Math.min(amount, Number(side.maximum));
    return Math.min(amount, base);
  }
  let tax = 0;
  let floor = 0;
  side.bands.forEach((b, i) => {
    if (base <= floor) return;
    const last = i === side.bands.length - 1;
    const top = last ? base : Math.min(base, Number(b.upTo));
    tax += ((top - floor) * Number(b.rate || 0)) / 100;
    floor = last ? floor : Number(b.upTo);
  });
  tax = Math.round(tax * 100) / 100;
  return tax - Math.min(Number(side.credit || 0), tax);
}

/** The version of each code that applies on a day: the latest that has started and not ended (what payroll uses). */
export function inForce(rules: Rule[], day: string): Set<string> {
  const chosen = new Map<string, Rule>();
  for (const r of rules) {
    const started = r.effective_from <= day && (!r.effective_to || day <= r.effective_to);
    const current = chosen.get(r.code);
    if (started && (!current || r.effective_from > current.effective_from)) chosen.set(r.code, r);
  }
  return new Set([...chosen.values()].map((r) => r.id));
}
