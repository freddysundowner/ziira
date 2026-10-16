/** Pure rules for the subscribers list and the actions on one subscriber. The server re-checks every one of them. */

export const FLAGS = ["trial_ending", "past_due", "churned", "unmanaged"] as const;

export interface SubscriberFilters {
  search: string;
  status: string;
  plan: string;
  edition: string;
  country: string;
  flag: string;
}

export const NO_FILTERS: SubscriberFilters = { search: "", status: "", plan: "", edition: "", country: "", flag: "" };

const KEYS = Object.keys(NO_FILTERS) as (keyof SubscriberFilters)[];

/** The filters held in the address (so a link from the dashboard, or a reload, keeps them). */
export function filtersFromParams(params: URLSearchParams): SubscriberFilters {
  const out = { ...NO_FILTERS };
  for (const key of KEYS) out[key] = params.get(key) ?? "";
  return out;
}

/** Only the filters that are set. */
export function filtersToParams(filters: SubscriberFilters): URLSearchParams {
  const params = new URLSearchParams();
  for (const key of KEYS) if (filters[key].trim()) params.set(key, filters[key].trim());
  return params;
}

/** The query the API takes: set filters only, a country in capitals, and the page as limit/offset. */
export function subscriberQuery(filters: SubscriberFilters, page: number, pageSize: number) {
  const query: Record<string, string | number> = { limit: pageSize, offset: page * pageSize };
  for (const key of KEYS) {
    const value = filters[key].trim();
    if (value) query[key] = key === "country" ? value.toUpperCase() : value;
  }
  return query as { search?: string; status?: string; plan?: string; edition?: string; country?: string; flag?: string; limit: number; offset: number };
}

export function hasFilters(filters: SubscriberFilters): boolean {
  return KEYS.some((k) => filters[k].trim() !== "");
}

export type SubscriberAction =
  | "start" | "changePlan" | "extendTrial" | "comp" | "coupon" | "syncPlan" | "issueInvoice"
  | "suspend" | "reactivate" | "cancel" | "uncancel" | "export" | "delete";

/** Which permission each action needs (the same split as the server's routes). */
export const ACTION_PERMISSION: Record<SubscriberAction, "platform.billing" | "platform.subscribers"> = {
  start: "platform.billing", changePlan: "platform.billing", extendTrial: "platform.billing", comp: "platform.billing", coupon: "platform.billing",
  syncPlan: "platform.billing", issueInvoice: "platform.billing",
  suspend: "platform.subscribers", reactivate: "platform.subscribers", cancel: "platform.subscribers", uncancel: "platform.subscribers",
  export: "platform.subscribers", delete: "platform.subscribers",
};

/** The actions that make sense for a subscriber in this state and that the operator's role may do. */
export function availableActions(sub: { status: string; cancel_at_period_end: boolean }, allowed: (permission: string) => boolean): SubscriberAction[] {
  const status = sub.status;
  const list: SubscriberAction[] = [];
  if (status === "unmanaged") list.push("start");
  else {
    const live = ["trialing", "active", "past_due", "grace"].includes(status);
    list.push("changePlan");
    if (status === "trialing") list.push("extendTrial");
    if (live) list.push("comp", "coupon");
    list.push("syncPlan");
    if (status !== "suspended" && live) list.push("suspend");
    if (["suspended", "cancelled", "expired"].includes(status)) list.push("reactivate");
    if (live) list.push(sub.cancel_at_period_end ? "uncancel" : "cancel");
    list.push("issueInvoice");
  }
  list.push("export", "delete");
  return list.filter((a) => allowed(ACTION_PERMISSION[a]));
}
