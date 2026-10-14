import { api, money, unwrap, useCan, useCompany, useQuery } from "@/sdk";

import { shortId } from "./lib";

/** Every branch of every company the user reaches, for pickers and for naming a branch from its id. */
export function useBranches() {
  const { companies } = useCompany();
  const branches = companies.flatMap((c) => c.branches.map((b) => ({ ...b, companyId: c.id })));
  const nameOf = (id: string | null | undefined) => (id ? branches.find((b) => b.id === id)?.name ?? shortId(id) : "—");
  return { branches, nameOf };
}

/** Formats an amount in the currency of the company it belongs to (the first company when none is named). */
export function useMoney() {
  const { company, companies } = useCompany();
  return (value: string | null | undefined, companyId?: string) =>
    money(value, (companies.find((c) => c.id === companyId) ?? company)?.currency);
}

/** Names of people from their ids. Only users who may manage users can read the list; others see a short id. */
export function useUserNames() {
  const can = useCan("users.manage");
  const users = useQuery({ enabled: can, retry: false, staleTime: 5 * 60_000, queryKey: ["users"], queryFn: () => unwrap(api.GET("/api/v1/users")) });
  return (id: string | null | undefined) => (id ? users.data?.find((u) => u.id === id)?.full_name ?? shortId(id) : "—");
}

/** The business's tills (devices). Readable by those who manage devices or sell; others get an empty list. */
export function useDevices(branchId?: string) {
  return useQuery({
    retry: false, staleTime: 60_000, queryKey: ["pos-devices", branchId ?? ""],
    queryFn: () => unwrap(api.GET("/api/v1/pos/devices", { params: { query: { branch_id: branchId || undefined } } })),
  });
}

/** Names a device from its id. */
export function useDeviceName() {
  const devices = useDevices();
  return (id: string) => devices.data?.find((d) => d.id === id)?.name ?? shortId(id);
}

/** The choices of one reason list (void, sale_return, price_override, till_variance). */
export function useReasons(category: string, enabled = true) {
  return useQuery({
    enabled, staleTime: 60_000, queryKey: ["reasons", category],
    queryFn: () => unwrap(api.GET("/api/v1/settings/reason-codes", { params: { query: { category } } })),
  });
}

/** Stores (inventory locations), to say where returned goods go back. Not everyone may read them, so a failure is quiet. */
export function useLocations(branchId: string | null | undefined, enabled = true) {
  return useQuery({
    enabled, retry: false, staleTime: 60_000, queryKey: ["inventory-locations", branchId ?? ""],
    queryFn: () => unwrap(api.GET("/api/v1/inventory/locations", { params: { query: { branch_id: branchId || undefined } } })),
  });
}

/** Tills to choose from in a filter, narrowed by branch and day. Quiet when the user may not list tills. */
export function useTillOptions({ branch, date }: { branch: string; date: string }) {
  return useQuery({
    retry: false, staleTime: 30_000, queryKey: ["pos-till-options", branch, date],
    queryFn: () => unwrap(api.GET("/api/v1/pos/tills", { params: { query: { branch_id: branch || undefined, business_date: date || undefined, limit: 100 } } })),
  });
}
