import { Badge, Button, type Column, formatDate, useTranslation } from "@/sdk";

import { hoursText } from "../lib/time";
import type { Attendance } from "../lib/types";

/** The columns every attendance table shares: times, hours, overtime, where the record came from, and Edit. */
export function useAttendanceColumns(onEdit: (row: Attendance) => void): Column<Attendance>[] {
  const { t } = useTranslation("people");
  return [
    { header: t("attendance.clockIn"), hideBelow: "sm", cell: (r) => (r.clock_in ? formatDate(r.clock_in, true) : "—") },
    { header: t("attendance.clockOut"), hideBelow: "md", cell: (r) => (r.clock_out ? formatDate(r.clock_out, true) : "—") },
    { header: t("attendance.hours"), align: "right", cell: (r) => hoursText(r.hours) },
    { header: t("attendance.overtime"), align: "right", hideBelow: "sm", cell: (r) => hoursText(r.overtime_hours) },
    { header: t("attendance.source"), hideBelow: "lg", cell: (r) => <Badge>{t(`attendance.sources.${r.source}`, r.source)}</Badge> },
    { header: "", align: "right", cell: (r) => <Button size="sm" variant="ghost" onClick={() => onEdit(r)}>{t("edit")}</Button> },
  ];
}
