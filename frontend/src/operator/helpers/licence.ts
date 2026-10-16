/** The licence issue form (text), what is wrong with it, and the request the API takes. */
import { dateToIso } from "./format";

export interface LicenceForm {
  customer: string;
  contact_email: string;
  basis: "plan" | "units";
  plan_code: string;
  edition: string;
  units: string[];
  max_users: string;
  max_branches: string;
  max_companies: string;
  perpetual: boolean;
  valid_until: string;
  update_until: string;
  grace_days: string;
  instance_id: string;
  notes: string;
}

export const emptyLicenceForm = (): LicenceForm => ({
  customer: "", contact_email: "", basis: "plan", plan_code: "", edition: "", units: [], max_users: "", max_branches: "", max_companies: "",
  perpetual: false, valid_until: "", update_until: "", grace_days: "30", instance_id: "", notes: "",
});

const whole = (v: string): number | null => (v.trim() === "" ? null : /^\d+$/.test(v.trim()) ? Number(v) : Number.NaN);

/** Field -> a key under "licences.errors". */
export function licenceProblems(f: LicenceForm): Record<string, string> {
  const errors: Record<string, string> = {};
  if (f.customer.trim().length < 2) errors.customer = "customer";
  if (f.contact_email.trim() && !/^\S+@\S+\.\S+$/.test(f.contact_email.trim())) errors.contact_email = "email";
  if (f.basis === "plan" && !f.plan_code) errors.plan_code = "plan";
  if (f.basis === "units" && !f.edition && f.units.length === 0) errors.units = "units";
  for (const key of ["max_users", "max_branches", "max_companies"] as const) {
    const n = whole(f[key]);
    if (n !== null && (Number.isNaN(n) || n < 1)) errors[key] = "limit";
  }
  if (!f.perpetual && !f.valid_until) errors.valid_until = "validUntil";
  const grace = whole(f.grace_days);
  if (grace === null || Number.isNaN(grace) || grace > 365) errors.grace_days = "grace";
  if (f.instance_id.length > 64) errors.instance_id = "instance";
  return errors;
}

export function toLicenceIn(f: LicenceForm) {
  return {
    customer: f.customer.trim(),
    contact_email: f.contact_email.trim() || null,
    plan_code: f.basis === "plan" ? f.plan_code : null,
    edition: f.basis === "units" ? f.edition || null : null,
    units: f.basis === "units" ? f.units : [],
    max_users: whole(f.max_users),
    max_branches: whole(f.max_branches),
    max_companies: whole(f.max_companies),
    valid_until: f.perpetual ? null : dateToIso(f.valid_until),
    update_until: dateToIso(f.update_until),
    grace_days: whole(f.grace_days) ?? 30,
    instance_id: f.instance_id.trim() || null,
    notes: f.notes.trim(),
  };
}
