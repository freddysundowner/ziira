/**
 * What the sign-up wizard knows: the answers, which step each belongs to, what is wrong with them, and the draft kept in
 * sessionStorage so a refresh does not lose them. The password (and its confirmation) is never written anywhere.
 */
import { confirmProblem, emailProblem, nameProblem, type Problem } from "./validators";

export const STEPS = ["need", "business", "account"] as const;
export type StepId = (typeof STEPS)[number];

export interface Values {
  edition: string;
  name: string;
  email: string;
  phone: string;
  role: string;
  password: string;
  confirm: string;
  business: string;
  country: string;
  currency: string;
  zone: string;
  calling: string;
  tax: string;
  branches: string;
  staff: string;
  kind: string;
  consent: boolean;
}

export type FieldKey = keyof Values;

export const EMPTY: Values = {
  edition: "full", name: "", email: "", phone: "", role: "", password: "", confirm: "", business: "", country: "", currency: "",
  zone: "", calling: "", tax: "", branches: "", staff: "", kind: "", consent: false,
};

export const FIELDS_OF: Record<StepId, FieldKey[]> = {
  need: ["edition"],
  business: ["business", "country", "currency", "zone", "calling", "kind"],
  // name, phone, role, tax, branches and staff are no longer asked here; they stay in the list so a server complaint still finds its step
  account: ["email", "password", "confirm", "consent", "name", "phone", "role", "tax", "branches", "staff"],
};

export const ROLES = ["owner", "manager", "accountant", "other"] as const;
export const BRANCH_SIZES = ["1", "2-5", "6-20", "more"] as const;
export const STAFF_SIZES = ["1-5", "6-20", "21-50", "more"] as const;
export const KINDS = ["retail", "wholesale", "services", "other"] as const;

/** The server's name for each field of the request, and our field for it (a 422 names `owner_name`, we call it `name`). */
const SERVER_FIELD: Record<string, FieldKey> = {
  edition: "edition", owner_name: "name", email: "email", phone: "phone", owner_role: "role", password: "password",
  business_name: "business", country: "country", currency: "currency", timezone: "zone", phone_country_code: "calling",
  tax_id: "tax", business_size: "branches", staff_size: "staff", business_type: "kind",
};

export function stepOf(field: FieldKey): StepId {
  return STEPS.find((s) => FIELDS_OF[s].includes(field)) ?? "account";
}

/** Our field and step for each field the server complained about, in the order of the wizard. */
export function serverProblems(fields: Record<string, string>): { field: FieldKey; message: string; step: StepId }[] {
  return Object.entries(fields)
    .flatMap(([name, message]) => (SERVER_FIELD[name] ? [{ field: SERVER_FIELD[name], message, step: stepOf(SERVER_FIELD[name]) }] : []))
    .sort((a, b) => STEPS.indexOf(a.step) - STEPS.indexOf(b.step));
}

export interface Context {
  /** The tax-number pattern of the chosen country's pack, when it has one. */
  taxPattern?: string;
  /** Whether the server accepted this password (null: not asked yet or not reachable). */
  passwordOk: boolean | null;
}

export type Problems = Partial<Record<FieldKey, Problem>>;

/** Everything wrong with the answers of one step (only the fields that have a problem appear). */
export function problemsOf(step: StepId, v: Values, ctx: Context): Problems {
  const out: Problems = {};
  const put = (key: FieldKey, problem: Problem) => { if (problem) out[key] = problem; };
  if (step === "business") {
    put("business", nameProblem(v.business, "business"));
    if (!v.country) put("country", { code: "country.required" });
    else if (!/^[A-Za-z]{3}$/.test(v.currency)) put("country", { code: "currency.required" });
  } else if (step === "account") {
    put("email", emailProblem(v.email));
    if (v.password.length < 8) put("password", { code: "password.short" });
    else if (ctx.passwordOk === false) put("password", { code: "password.refused" });
    put("confirm", confirmProblem(v.password, v.confirm));
    if (!v.consent) put("consent", { code: "consent.required" });
  }
  return out;
}

export const isValid = (step: StepId, v: Values, ctx: Context) => Object.keys(problemsOf(step, v, ctx)).length === 0;

/** The first step whose answers are not valid yet (the last step when all are). */
export function firstIncomplete(v: Values, ctx: Context): StepId {
  return STEPS.find((s) => s !== "account" && !isValid(s, v, ctx)) ?? "account";
}

// --------------------------------------------------------------------------- the draft
const DRAFT_KEY = "ziira.register.draft";
const SECRET: FieldKey[] = ["password", "confirm", "consent"];

/** Keep the answers (never the password, its confirmation or the consent) for a refresh. */
export function saveDraft(v: Values, step: StepId): void {
  try {
    const kept = Object.fromEntries(Object.entries(v).filter(([key]) => !SECRET.includes(key as FieldKey)));
    sessionStorage.setItem(DRAFT_KEY, JSON.stringify({ ...kept, step }));
  } catch {
    /* storage can be unavailable: the wizard works without it */
  }
}

export function clearDraft(): void {
  try { sessionStorage.removeItem(DRAFT_KEY); } catch { /* nothing to clear */ }
}

export function loadDraft(): { values: Values; step: StepId } | null {
  try {
    const raw = sessionStorage.getItem(DRAFT_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw) as Record<string, unknown>;
    const values: Values = { ...EMPTY };
    for (const key of Object.keys(EMPTY) as FieldKey[]) {
      if (!SECRET.includes(key) && typeof data[key] === "string") Object.assign(values, { [key]: data[key] });
    }
    const step = STEPS.find((s) => s === data.step) ?? "need";
    return { values, step };
  } catch {
    return null;
  }
}
