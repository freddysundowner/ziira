import { useAccess } from "@/sdk";

/** What this user may do with customer accounts. They need the Point of sale unit, which owns invoices and receipts. */
export function useReceivables() {
  const { enabledUnits, can } = useAccess();
  const on = enabledUnits.has("pos");
  return { canView: on && can("receivables.view"), canReceive: on && can("receivables.manage") };
}
