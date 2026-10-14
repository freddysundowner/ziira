import { money, useCurrency } from "@/sdk";

/** An amount in the currency of the company it belongs to. */
export function Amount({ value, companyId }: { value: string | null | undefined; companyId?: string }) {
  return <>{money(value, useCurrency(companyId))}</>;
}
