import type { Schemas } from "@/sdk";

export type BillingBanner = Schemas["Banner"];

/** Pages a suspended owner may stay on: paying, and their own account (to sign out or fix a password). */
const ALLOWED = ["/admin/billing", "/admin/account"];

/** A suspended business can only pay, so its owner is sent straight to Plan & billing instead of meeting refusals page after page. */
export function mustGoToBilling(banner: BillingBanner | null | undefined, pathname: string): boolean {
  if (!banner || banner.status !== "suspended") return false;
  return !ALLOWED.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

export type Notice = { tone: "info" | "warn" | "bad"; key: string; params: Record<string, string | number>; text?: string };

/** What the owner is told above every page: a trial ending in a week or less, an ended trial or plan, an overdue payment. Null: nothing to say. */
export function noticeFor(banner: BillingBanner | null | undefined, formatDate: (v: string) => string, onHome = false): Notice | null {
  if (!banner) return null;
  const date = banner.date ? formatDate(banner.date) : "";
  switch (banner.kind) {
    case "trial":
      return banner.days_left !== null && banner.days_left !== undefined && banner.days_left <= 7
        ? { tone: banner.days_left <= 3 ? "warn" : "info", key: banner.days_left === 0 ? "billing.notice.trialToday" : "billing.notice.trialEnding", params: { count: banner.days_left } }
        : onHome && banner.message ? { tone: "info", key: "", params: {}, text: banner.message } : null;     // Home also says when a longer trial ends
    case "trial_ended": return { tone: "bad", key: "billing.notice.trialEnded", params: { date } };
    case "suspended": return { tone: "bad", key: date ? "billing.notice.suspended" : "billing.notice.suspendedNoDate", params: { date } };
    case "past_due":
    case "grace": return { tone: "warn", key: "billing.notice.overdue", params: {} };
    default: return banner.level === "info" ? null : { tone: banner.level === "blocked" ? "bad" : "warn", key: "", params: {}, text: banner.message };
  }
}

/** A notice may be hidden for the session only when it is not a block: never an ended trial, an ended plan or an overdue payment. */
export function dismissible(banner: BillingBanner | null | undefined, tone: Notice["tone"]): boolean {
  return !!banner && tone !== "bad" && banner.kind === "trial";
}
