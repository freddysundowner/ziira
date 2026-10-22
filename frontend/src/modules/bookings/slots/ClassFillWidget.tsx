import { api, HomeBox, type SlotProps, unwrap, useQuery, useTranslation } from "@/sdk";

import { useBranch } from "../hooks";
import { clock, dayOf } from "../lib";

const NEXT = 5;
const DAYS = 7;

/** Home box: how full the next classes are (places taken over places in all, for the next few classes in the coming week). */
export default function ClassFillWidget({ variant }: SlotProps) {
  const { t } = useTranslation("bookings");
  const { branchId, zone } = useBranch();
  const list = useQuery({
    queryKey: ["bookings", "classes", "widget", branchId], enabled: !!branchId, refetchInterval: 2 * 60_000,
    queryFn: () => {
      const from = new Date();
      return unwrap(api.GET("/api/v1/bookings/sessions", { params: { query: { branch_id: branchId, start: from.toISOString(), end: new Date(from.getTime() + DAYS * 86_400_000).toISOString() } } }));
    },
  });
  const next = (list.data ?? []).filter((s) => s.status !== "cancelled" && s.capacity > 0).sort((a, b) => a.starts_at.localeCompare(b.starts_at)).slice(0, NEXT);
  const places = next.reduce((n, s) => n + s.capacity, 0);
  const taken = next.reduce((n, s) => n + (s.capacity - s.free), 0);
  const percent = places > 0 ? Math.round((taken / places) * 100) : 0;
  const waiting = next.reduce((n, s) => n + s.waiting, 0);
  return (
    <HomeBox
      variant={variant} to="/classes" value={next.length === 0 ? "—" : `${percent}%`} tone={places > 0 && percent < 40 ? "warn" : undefined}
      loading={list.isLoading || !branchId} error={list.error?.message} onRetry={() => void list.refetch()}
      clear={next.length === 0 ? t("widget.noClasses") : undefined}
      hint={waiting > 0 ? t("widget.classWaiting", { count: waiting }) : t("widget.classHint", { taken, places, count: next.length })}
      rows={next.map((s) => ({ key: s.id, left: `${dayOf(s.starts_at, zone) === dayOf(new Date(), zone) ? "" : `${new Intl.DateTimeFormat(undefined, { weekday: "short", timeZone: zone }).format(new Date(s.starts_at))} `}${clock(s.starts_at, zone)} ${s.name}`, right: `${s.capacity - s.free}/${s.capacity}` }))}
      openLabel={t("widget.openClasses")} />
  );
}
