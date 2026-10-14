import { Link } from "react-router-dom";

import { ErrorState, quantity, Skeleton, useTranslation } from "@/sdk";

import { useLowStock } from "../useLowStock";

/** Home-page box: how many products are at or under their reorder level, and the worst five. */
export default function LowStockWidget() {
  const { t } = useTranslation("inventory");
  const low = useLowStock();
  if (low.error) return <ErrorState message={low.error} onRetry={low.retry} />;
  if (!low.rows) return <Skeleton className="h-16 w-full" />;
  if (low.rows.length === 0) return <p className="text-sm text-ok">{t("allGood")}</p>;
  return (
    <div className="space-y-3">
      <p><span className="tnum text-3xl font-semibold text-warn">{low.rows.length}</span> <span className="text-sm text-muted">{t("productsLow", { count: low.rows.length })}</span></p>
      <ul className="divide-y divide-line text-sm">
        {low.rows.slice(0, 5).map((r) => (
          <li key={r.product.id} className="flex items-center justify-between gap-3 py-1.5">
            <Link className="truncate hover:underline" to={`/products/${r.product.id}`}>{r.product.name}</Link>
            <span className="tnum shrink-0 text-muted">{quantity(r.onHand)} / {quantity(r.reorderLevel)}</span>
          </li>
        ))}
      </ul>
      <Link className="text-sm text-brand hover:underline" to="/stock">{t("seeAll")}</Link>
    </div>
  );
}
