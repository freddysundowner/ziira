import type { Schemas } from "@/sdk";

/** The generated name of a schema: the plain name, or the prefixed one the generator uses while another module shares the plain name. */
type Named<Plain extends string> = `ziira__modules__timebilling__api__schemas__${Plain}` extends keyof Schemas ? Schemas[`ziira__modules__timebilling__api__schemas__${Plain}`] : `TimeBilling${Plain}` extends keyof Schemas ? Schemas[`TimeBilling${Plain}`] : Plain extends keyof Schemas ? Schemas[Plain] : never;

export type Entry = Named<"EntryOut">;
export type Expense = Named<"ExpenseOut">;
export type Project = Schemas["ProjectOut"];
export type Week = Schemas["WeekOut"];
export type WeekRow = Schemas["WeekRow"];
export type Settings = Named<"SettingsOut">;
export type Timer = Schemas["TimerOut"];
export type Review = Schemas["ReviewOut"];
export type ReviewLine = Schemas["ReviewLineOut"];
export type Retainer = Schemas["RetainerOut"];
export type Rate = Schemas["RateOut"];
export type Client = Schemas["ClientOut"];
export type Staff = Schemas["StaffOut"];
export type Milestone = Schemas["MilestoneOut"];
export type RetainerTxn = Schemas["RetainerTxnOut"];
export type Unbilled = Schemas["UnbilledOut"];

export const WEEK_STATES = ["draft", "submitted", "approved", "rejected"] as const;
export const PROJECT_STATES = ["active", "on_hold", "completed", "archived"] as const;
export type Task = Schemas["TimeBillingTaskOut"];
export type Recurrence = Schemas["TimeBillingRecurrenceOut"];
export type Template = Schemas["TimeBillingTemplateOut"];
export type Activity = Schemas["TimeBillingActivityOut"];
export type Snippet = Schemas["TimeBillingSnippetOut"];
export type OwnerSummary = Schemas["TimeBillingOwnerOut"];
export type RealisationRow = Schemas["TimeBillingRealisationRow"];
export type Setup = Schemas["TimeBillingSetupOut"];
export type MissingDay = Schemas["TimeBillingMissingDayOut"];

export const BILLING_MODES = ["time_and_materials", "fixed_fee", "capped_fee", "retainer"] as const;
export const FREQUENCIES = ["monthly", "quarterly", "annual"] as const;
export const GROUPINGS = ["project", "person", "task", "day"] as const;
