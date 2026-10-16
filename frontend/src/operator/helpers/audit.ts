/** The filters of the audit trail screen, and how they become a query for the list and the CSV download. */
export interface AuditFilters {
  operator: string;
  action: string;
  target: string;
  outcome: string;
  from: string;
  to: string;
}

export const NO_FILTERS: AuditFilters = { operator: "", action: "", target: "", outcome: "", from: "", to: "" };

/** Only the filters that have a value, trimmed, named as the API names them. */
export function auditQuery(f: AuditFilters): Record<string, string> {
  const out: Record<string, string> = {};
  const put = (key: string, value: string) => { if (value.trim()) out[key] = value.trim(); };
  put("operator", f.operator);
  put("action", f.action);
  put("target", f.target);
  put("outcome", f.outcome);
  put("date_from", f.from);
  put("date_to", f.to);
  return out;
}

export const hasFilters = (f: AuditFilters): boolean => Object.keys(auditQuery(f)).length > 0;

/** The end date is before the start date: the server refuses it, so the screen says so first. */
export const rangeProblem = (f: AuditFilters): boolean => f.from !== "" && f.to !== "" && f.to < f.from;

/** The path for the CSV download with the same filters. */
export function exportPath(f: AuditFilters): string {
  const query = new URLSearchParams(auditQuery(f)).toString();
  return `/api/v1/operator/audit/export${query ? `?${query}` : ""}`;
}

/** "plan.update" -> "Plan update": a readable action when the screen has no translation for it. */
export function actionLabel(action: string): string {
  const text = action.replace(/[._-]+/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}
