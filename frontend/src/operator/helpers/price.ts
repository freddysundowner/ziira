/** Price rows: which are in force, which are scheduled, and the form to add one. Prices are append-only and effective-dated. */
import { dateToIso } from "./format";

export type PriceState = "current" | "scheduled" | "withdrawn" | "superseded";

export function priceState(price: { id?: string | null; effective_from: string; withdrawn?: boolean }, currentIds: ReadonlySet<string>, now: Date = new Date()): PriceState {
  if (new Date(price.effective_from).getTime() > now.getTime()) return "scheduled";
  if (price.withdrawn) return "withdrawn";
  return price.id && currentIds.has(price.id) ? "current" : "superseded";
}

export interface PriceForm {
  currency: string;
  interval: string;
  amount: string;
  tax_inclusive: boolean;
  effective_from: string;
  withdrawn: boolean;
}

export const emptyPriceForm = (interval = "month"): PriceForm => ({ currency: "", interval, amount: "", tax_inclusive: false, effective_from: "", withdrawn: false });

/** Keys under "plans.price.errors". */
export function priceProblems(f: PriceForm): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!/^[A-Za-z]{3}$/.test(f.currency.trim())) errors.currency = "currency";
  if (!f.interval) errors.interval = "interval";
  if (!f.withdrawn && !/^\d+(\.\d{1,2})?$/.test(f.amount.trim())) errors.amount = "amount";
  return errors;
}

/** A withdrawn price carries amount zero (it only says "stop offering this from the date"). */
export function toPriceIn(f: PriceForm) {
  return {
    currency: f.currency.trim().toUpperCase(),
    interval: f.interval as "month" | "year" | "one_time",
    amount: f.withdrawn ? "0" : f.amount.trim(),
    tax_inclusive: f.tax_inclusive,
    effective_from: dateToIso(f.effective_from),
    withdrawn: f.withdrawn,
  };
}
