import { Link } from "react-router-dom";

import { api, ErrorState, quantity, Skeleton, type SlotProps, unwrap, useQuery, useTranslation } from "@/sdk";

/** How far ahead the Home box looks. */
const DAYS_AHEAD = 90;

/** Home-page box: batches still on the shelf that expire within three months (or already have), earliest first. */
export default function ExpiringWidget({ variant }: SlotProps) {
  const { t } = useTranslation("inventory");
  const rows = useQuery({
    queryKey: ["inv-expiring", DAYS_AHEAD], staleTime: 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/inventory/expiring", { params: { query: { days: DAYS_AHEAD, limit: 200 } } })),
  });
  if (rows.error) return <ErrorState message={rows.error.message} onRetry={() => void rows.refetch()} />;
  if (!rows.data) return <Skeleton className="h-16 w-full" />;
  const list = rows.data;
  const expired = list.filter((r) => r.days_left < 0).length;
  if (list.length === 0) {
    return variant === "stat"
      ? <Link to="/stock" className="block"><p className="tnum text-2xl font-semibold">0</p><p className="mt-1 text-xs text-ok">{t("expiringNone")}</p></Link>
      : <p data-clear className="text-sm text-ok">{t("expiringNone")}</p>;
  }
  if (variant === "stat") {
    return (
      <Link to="/stock" className="block">
        <p className={`tnum text-2xl font-semibold ${expired > 0 ? "text-bad" : "text-warn"}`}>{list.length}</p>
        <p className="mt-1 truncate text-xs text-muted">{expired > 0 ? t("expiringSomeGone", { count: expired }) : t("expiringBatches", { count: list.length })}</p>
      </Link>
    );
  }
  return (
    <div className="space-y-3">
      <p><span className={`tnum text-3xl font-semibold ${expired > 0 ? "text-bad" : "text-warn"}`}>{list.length}</span> <span className="text-sm text-muted">{t("expiringBatches", { count: list.length })}</span></p>
      <ul className="divide-y divide-line text-sm">
        {list.slice(0, 5).map((r) => (
          <li key={`${r.batch_id}-${r.location_id}`} className="flex items-center justify-between gap-3 py-1.5">
            <Link className="truncate hover:underline" to={`/products/${r.product_id}`}>{r.product_name ?? r.sku} <span className="text-muted">({r.batch_no})</span></Link>
            <span className={`tnum shrink-0 ${r.days_left < 0 ? "text-bad" : "text-muted"}`}>{r.days_left < 0 ? t("expiredAgo", { count: -r.days_left }) : t("expiresIn", { count: r.days_left })} · {quantity(r.quantity)}</span>
          </li>
        ))}
      </ul>
      <Link className="text-sm text-brand-strong hover:underline" to="/stock">{t("seeAll")}</Link>
    </div>
  );
}
