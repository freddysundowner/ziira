import type { Leave } from "./types";

export const pad = (n: number) => String(n).padStart(2, "0");
export const daysInMonth = (year: number, month: number) => new Date(year, month, 0).getDate();

/** First and last day of a month given as "YYYY-MM", as YYYY-MM-DD. */
export function monthBounds(ym: string): { from: string; to: string } {
  const [y = 0, m = 1] = ym.split("-").map(Number);
  return { from: `${ym}-01`, to: `${ym}-${pad(daysInMonth(y, m))}` };
}

export function shiftMonth(ym: string, by: number): string {
  const [y = 0, m = 1] = ym.split("-").map(Number);
  const d = new Date(y, m - 1 + by, 1);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}`;
}

export interface LeaveRow {
  employeeId: string;
  /** day of month -> the request that covers it */
  days: Map<number, Leave>;
}

/** Which days of a month each employee is on (or has asked for) leave. Rejected and cancelled requests are left out. */
export function leaveGrid(leaves: readonly Leave[], ym: string): LeaveRow[] {
  const { from, to } = monthBounds(ym);
  const rows = new Map<string, LeaveRow>();
  for (const leave of leaves) {
    if (leave.status === "rejected" || leave.status === "cancelled" || leave.end_date < from || leave.start_date > to) continue;
    const row = rows.get(leave.employee_id) ?? { employeeId: leave.employee_id, days: new Map() };
    rows.set(leave.employee_id, row);
    const first = leave.start_date < from ? 1 : Number(leave.start_date.slice(8));
    const last = leave.end_date > to ? Number(to.slice(8)) : Number(leave.end_date.slice(8));
    for (let d = first; d <= last; d++) {
      const current = row.days.get(d);
      if (!current || (current.status !== "approved" && leave.status === "approved")) row.days.set(d, leave);
    }
  }
  return [...rows.values()];
}

/** Weekday number of a day in the month (0 = Sunday), to shade weekends. */
export const weekday = (ym: string, day: number): number => {
  const [y = 0, m = 1] = ym.split("-").map(Number);
  return new Date(y, m - 1, day).getDay();
};
