import { useMemo } from "react";

import { lowStockRows } from "./logic";
import { useRange } from "./lookups";

/** Low-stock rows for the Stock screen and the dashboard widget; one pair of cached requests serves both. */
export function useLowStock(enabled = true) {
  const { products, balances } = useRange(enabled);
  const rows = useMemo(() => (products.data && balances.data ? lowStockRows(products.data, balances.data) : undefined), [products.data, balances.data]);
  return {
    rows,
    loading: products.isLoading || balances.isLoading,
    error: products.error?.message ?? balances.error?.message ?? null,
    retry: () => { void products.refetch(); void balances.refetch(); },
  };
}
