import type { Schemas } from "@/sdk";

export type Claim = Schemas["ClaimsClaimOut"];
export type ClaimSummary = Schemas["ClaimsSummaryOut"];
export type Estimate = Schemas["ClaimsEstimateOut"];
export type EstimateLine = Schemas["ClaimsLineOut"];
export type LineHistory = Schemas["ClaimsLineHistoryOut"];
export type Payer = Schemas["ClaimsPayerOut"];
export type Settings = Schemas["ClaimsSettingsOut"];
export type Run = Schemas["ClaimsInvoiceRunOut"];
export type ShortPay = Schemas["ClaimsShortPayOut"];
export type Owed = Schemas["ClaimsOwedOut"];
export type AgeingRow = Schemas["ClaimsAgeingRowOut"];
export type Billing = Schemas["ClaimsBillingOut"];
export type ClaimLink = Schemas["ClaimsLinkOut"];
export type ClaimEvent = Schemas["ClaimsEventOut"];
export type PayerStatement = Schemas["ClaimsPayerStatementOut"];

/** The kinds of line on an estimate, in the order the editor offers them. */
export const LINE_KINDS = ["labour", "parts", "paint", "sundries", "other"] as const;
export type LineKind = (typeof LINE_KINDS)[number];

export const PART_CLASSES = ["genuine", "aftermarket", "used"] as const;
export const ANSWERS = ["approved", "countered", "rejected", "needs_information"] as const;
export type AnswerState = (typeof ANSWERS)[number];
export const VIAS = ["phone", "email", "portal", "in_person", "message", "letter", "other"] as const;
export const CLOSE_REASONS = ["total_loss", "salvage", "cash_in_lieu", "rejected", "withdrawn", "cancelled", "written_off"] as const;
export const STATUSES = ["draft", "open", "authorised", "completed", "invoiced", "settled", "closed"] as const;
