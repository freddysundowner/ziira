import { HomeBox, type SlotProps, useTranslation } from "@/sdk";

import { FRONT_DESK_PATH } from "../public";
import { useDeskBoard } from "./useDeskBoard";

/** Home box: the people (or rooms) free right now, and for how long. Counts only those working at this moment. */
export default function FreeNowWidget({ variant }: SlotProps) {
  const { t } = useTranslation("bookings");
  const { board } = useDeskBoard();
  const people = board.data?.resources ?? [];
  const working = people.filter((p) => p.state !== "off");
  const free = working.filter((p) => p.state === "free");
  const none = !!board.data && working.length === 0;
  return (
    <HomeBox
      variant={variant} to={FRONT_DESK_PATH} value={free.length}
      loading={board.isLoading} error={board.error?.message} onRetry={() => void board.refetch()}
      clear={none ? t("widget.nobodyWorking") : undefined}
      hint={free.length === 0 ? t("widget.allBusy") : t("widget.ofWorking", { count: working.length, names: free.slice(0, 3).map((p) => p.name).join(", ") })}
      rows={free.slice(0, 5).map((p) => ({ key: p.resource_id, left: p.name, right: p.free_for_minutes != null ? t("widget.freeFor", { count: p.free_for_minutes }) : t("widget.freeRestOfDay") }))}
      openLabel={t("widget.open")} />
  );
}
