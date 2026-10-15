import { api, ApiError, errorMessage, type Option, unwrap, useQuery } from "@/sdk";

export const fetchAccounts = (companyId: string, includeInactive: boolean) =>
  unwrap(api.GET("/api/v1/finance/accounts", { params: { query: { company_id: companyId, include_inactive: includeInactive } } }));
export type Account = Awaited<ReturnType<typeof fetchAccounts>>[number];

/** The company's chart of accounts. Disabled until a company is known. */
export function useAccounts(companyId: string, includeInactive = false) {
  return useQuery({ enabled: !!companyId, queryKey: ["finance", "accounts", companyId, includeInactive], queryFn: () => fetchAccounts(companyId, includeInactive) });
}

export const accountLabel = (a: Pick<Account, "code" | "name">) => `${a.code} · ${a.name}`;

/** Where money is kept: the accounts a bank statement can be checked against. */
export const MONEY_SUBTYPES = ["cash", "bank", "mobile_money_clearing", "card_clearing"];
/** Expense accounts the system posts by itself (cost of goods, stock shrinkage, price variances, till variances, employer payroll costs): not categories for an expense a person records. */
export const SYSTEM_EXPENSE_SUBTYPES = ["cogs", "shrinkage", "purchase_variance", "till_variance", "payroll_employer_costs"];

/**
 * Accounts as combobox options. `types` limits them (for example only expense accounts), `subtypes` keeps only those kinds and
 * `exceptSubtypes` leaves some out; control accounts are left out when `postable`.
 */
export function accountOptions(
  accounts: readonly Account[] | undefined,
  opts: { types?: string[]; postable?: boolean; subtypes?: string[]; exceptSubtypes?: string[] } = {},
): Option[] {
  return (accounts ?? [])
    .filter((a) => a.is_active && (!opts.types || opts.types.includes(a.type)) && !(opts.postable && a.is_control)
      && (!opts.subtypes || opts.subtypes.includes(a.subtype ?? "")) && !(opts.exceptSubtypes && opts.exceptSubtypes.includes(a.subtype ?? "")))
    .sort((x, y) => x.code.localeCompare(y.code, undefined, { numeric: true }))
    .map((a) => ({ value: a.id, label: accountLabel(a), hint: a.type }));
}

export function accountNames(accounts: readonly Account[] | undefined): Map<string, string> {
  return new Map((accounts ?? []).map((a) => [a.id, accountLabel(a)]));
}

/**
 * Statements that can also be downloaded as CSV are typed `unknown` in the generated API types (JSON | CSV), so say what the JSON is.
 */
export function json<T>(request: Promise<{ data?: unknown; error?: unknown; response: Response }>): Promise<T> {
  return unwrap(request as Promise<{ data?: T; error?: unknown; response: Response }>);
}

type Download = Promise<{ data?: unknown; error?: unknown; response: Response }>;

/** Save a CSV the API produced. The API needs the sign-in token, so this goes through the API client and a Blob, never a plain link. */
export async function downloadFile(request: Download, fallbackName: string): Promise<void> {
  const { data, error, response } = await request;
  if (!response.ok) {
    let body = error;
    if (typeof body === "string") {
      try { body = JSON.parse(body); } catch { body = undefined; }
    }
    throw new ApiError(errorMessage(body, response.status), response.status);
  }
  const name = /filename="?([^";]+)"?/.exec(response.headers.get("Content-Disposition") ?? "")?.[1] ?? fallbackName;
  const url = URL.createObjectURL(data as Blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

