import { money, useCurrency } from "@/sdk";

/** An amount in the currency of the company that owns the document. */
export function Money({ value, companyId }: { value: string | null | undefined; companyId?: string }) {
  return <>{money(value, useCurrency(companyId))}</>;
}
