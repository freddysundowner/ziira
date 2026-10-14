import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api, Card, cx, EmptyState, ErrorState, IconButton, SkeletonRows, today, unwrap, useQuery, useTranslation } from "@/sdk";

import { daysInMonth, leaveGrid, monthBounds, shiftMonth, weekday } from "../lib/calendar";
import type { LeaveType } from "../lib/types";

/** A month at a glance: one row per employee with leave, one column per day. */
export function OverviewPanel({ types, names }: { types: LeaveType[]; names: (id: string) => string }) {
  const { t } = useTranslation("people");
  const [month, setMonth] = useState(today().slice(0, 7));
  const { from, to } = monthBounds(month);
  const [y = 0, m = 1] = month.split("-").map(Number);
  const days = Array.from({ length: daysInMonth(y, m) }, (_, i) => i + 1);
  const leaves = useQuery({
    queryKey: ["people", "leave", "overview", month],
    queryFn: () => unwrap(api.GET("/api/v1/people/leave-requests", { params: { query: { date_from: from, date_to: to, limit: 500 } } })),
  });
  const rows = leaveGrid(leaves.data ?? [], month).sort((a, b) => names(a.employeeId).localeCompare(names(b.employeeId)));
  const typeName = (id: string) => types.find((x) => x.id === id)?.name ?? "";
  const label = new Intl.DateTimeFormat(document.documentElement.lang || undefined, { month: "long", year: "numeric" }).format(new Date(y, m - 1, 1));

  return (
    <Card flush title={label} actions={<>
      <IconButton label={t("previous")} onClick={() => setMonth(shiftMonth(month, -1))}><ChevronLeft className="h-4 w-4" /></IconButton>
      <button className="rounded-lg px-2 py-1 text-xs font-medium hover:bg-sunken" onClick={() => setMonth(today().slice(0, 7))}>{t("thisMonth")}</button>
      <IconButton label={t("next")} onClick={() => setMonth(shiftMonth(month, 1))}><ChevronRight className="h-4 w-4" /></IconButton>
    </>}>
      {leaves.error ? <ErrorState message={leaves.error.message} onRetry={() => void leaves.refetch()} /> : !leaves.data ? <SkeletonRows /> : rows.length === 0 ? (
        <EmptyState title={t("leave.overviewEmpty")} hint={t("leave.overviewEmptyHint")} />
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="border-b border-line text-muted">
                  <th className="sticky left-0 z-10 min-w-[10rem] bg-surface px-3 py-2 text-left font-medium">{t("leave.employee")}</th>
                  {days.map((d) => <th key={d} className={cx("min-w-[1.6rem] px-0.5 py-2 text-center font-medium", [0, 6].includes(weekday(month, d)) && "bg-sunken/60")}>{d}</th>)}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.employeeId} className="border-b border-line last:border-0">
                    <th scope="row" className="sticky left-0 z-10 bg-surface px-3 py-2 text-left text-sm font-medium"><Link className="hover:underline" to={`/employees/${r.employeeId}`}>{names(r.employeeId)}</Link></th>
                    {days.map((d) => {
                      const leave = r.days.get(d);
                      return (
                        <td key={d} className={cx("h-8 border-l border-line/50 p-0.5", [0, 6].includes(weekday(month, d)) && "bg-sunken/60")}>
                          {leave && <div title={`${typeName(leave.leave_type_id)} · ${t(`state.${leave.status}`)}`} className={cx("h-full min-h-[1.5rem] rounded", leave.status === "approved" ? "bg-brand" : "bg-warn-soft ring-1 ring-inset ring-warn")} />}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex gap-4 border-t border-line px-4 py-2.5 text-xs text-muted">
            <span className="flex items-center gap-1.5"><span className="h-3 w-3 rounded bg-brand" />{t("state.approved")}</span>
            <span className="flex items-center gap-1.5"><span className="h-3 w-3 rounded bg-warn-soft ring-1 ring-inset ring-warn" />{t("state.pending")}</span>
          </div>
        </>
      )}
    </Card>
  );
}
