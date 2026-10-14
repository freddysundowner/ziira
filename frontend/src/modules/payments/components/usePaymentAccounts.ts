import { api, unwrap, useQuery } from "@/sdk";

/** The business's payment accounts (cached; used to name accounts in lists and fill account pickers). */
export function usePaymentAccounts(options: { kind?: string; includeInactive?: boolean; enabled?: boolean } = {}) {
  const { kind, includeInactive, enabled = true } = options;
  return useQuery({
    enabled, queryKey: ["payment-accounts", kind ?? "all", !!includeInactive],
    queryFn: () => unwrap(api.GET("/api/v1/payments/accounts", { params: { query: { kind, include_inactive: includeInactive } } })),
  });
}
