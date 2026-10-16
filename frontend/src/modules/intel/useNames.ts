import { useCompany } from "@/sdk";

/** Branch names and company currencies, so a card says "Ruiru" and "KES 1,200.00" and never an id. */
export function useNames() {
  const { companies } = useCompany();
  return {
    companies,
    branchName: (id: string | null | undefined) => (id ? companies.flatMap((c) => c.branches).find((b) => b.id === id)?.name : undefined),
    currencyOf: (companyId: string | null | undefined) => companies.find((c) => c.id === companyId)?.currency ?? companies[0]?.currency,
  };
}
