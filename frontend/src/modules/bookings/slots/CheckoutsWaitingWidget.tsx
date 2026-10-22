import { HomeBox, type SlotProps, useTranslation } from "@/sdk";

import { FRONT_DESK_PATH } from "../public";
import { useDeskBoard } from "./useDeskBoard";

/** Home box: visits that are finished (or being served) and not billed yet. */
export default function CheckoutsWaitingWidget({ variant }: SlotProps) {
  const { t } = useTranslation("bookings");
  const { board } = useDeskBoard();
  const rows = board.data?.to_bill ?? [];
  return (
    <HomeBox
      variant={variant} to={FRONT_DESK_PATH} value={rows.length} tone={rows.length > 0 ? "warn" : undefined}
      loading={board.isLoading} error={board.error?.message} onRetry={() => void board.refetch()}
      clear={rows.length === 0 ? t("widget.nothingToBill") : undefined}
      hint={rows.length > 0 ? t("widget.toBillHint", { name: rows[0].client_name ?? rows[0].service }) : undefined}
      rows={rows.slice(0, 5).map((r) => ({ key: r.appointment_id, left: `${r.client_name ?? "—"} · ${r.service}`, right: r.waited_minutes > 0 ? t("widget.waitedMin", { count: r.waited_minutes }) : undefined }))}
      openLabel={t("widget.open")} />
  );
}
