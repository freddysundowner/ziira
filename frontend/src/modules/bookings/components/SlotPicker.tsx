import { api, cx, Spinner, unwrap, useQuery, useTranslation } from "@/sdk";

import { clock } from "../lib";

export interface PickedSlot { startIso: string; resourceIds: string[] }

/** The free start times of a service on a day, as buttons. The front desk sees every free time (notice and distance are not applied). */
export function SlotPicker({ offerId, branchId, day, resourceId, zone, value, onChange }: {
  offerId: string; branchId: string; day: string; resourceId?: string; zone?: string; value: string; onChange: (slot: PickedSlot) => void;
}) {
  const { t } = useTranslation("bookings");
  const query = useQuery({
    queryKey: ["bookings", "availability", offerId, branchId, day, resourceId ?? ""], enabled: !!offerId && !!day,
    queryFn: () => unwrap(api.GET("/api/v1/bookings/availability", { params: { query: { offer_id: offerId, date: day, branch_id: branchId || undefined, resource_id: resourceId || undefined } } })),
  });
  if (query.isLoading) return <div className="flex items-center gap-2 text-sm text-muted"><Spinner /> {t("form.loadingTimes")}</div>;
  if (query.error) return <p role="alert" className="text-sm text-bad">{query.error.message} <button type="button" className="underline" onClick={() => void query.refetch()}>{t("retry")}</button></p>;
  const slots = query.data ?? [];
  if (slots.length === 0) return <p className="text-sm text-muted">{t("form.noTimes")}</p>;
  return (
    <div className="flex flex-wrap gap-1.5" role="group" aria-label={t("form.freeTimes")}>
      {slots.map((s) => {
        const picked = new Date(s.start).getTime() === new Date(value || 0).getTime();
        return (
          <button key={s.start} type="button" aria-pressed={picked} onClick={() => onChange({ startIso: s.start, resourceIds: s.resource_ids })}
            className={cx("h-8 rounded-md border px-2.5 text-sm", picked ? "border-brand bg-brand text-brand-ink" : "border-line bg-surface hover:bg-sunken")}>
            {clock(s.start, zone)}
          </button>
        );
      })}
    </div>
  );
}
