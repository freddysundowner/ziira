/** Small pure rules of the Lead Intel screens, kept apart so they can be tested. */

export type SetupStatus = "requested" | "awaiting_code" | "code_sent" | "connected" | "active" | "failed" | "cancelled" | "disconnected";

/** A request Lead Intel is still working on: the screen asks again every few seconds. */
export const isWorking = (status: string | undefined): boolean => status === "requested" || status === "awaiting_code" || status === "connected";

/** A connection that ended without a number being connected: the person may start again. */
export const canStartAgain = (status: string | undefined): boolean => status === undefined || status === "failed" || status === "cancelled" || status === "disconnected";

/** Which step of the wizard is open: 1 key, 2 number, 3 connected. */
export function currentStep(keySaved: boolean, status: string | undefined): 1 | 2 | 3 {
  if (!keySaved) return 1;
  return status === "active" ? 3 : 2;
}

/** Digits only, as Lead Intel wants the country code and the number. */
export const digits = (value: string): string => value.replace(/\D/g, "");

/** Template counts by status, for the summary line. */
export function countByStatus(rows: { status: string }[]): Record<string, number> {
  const counts: Record<string, number> = { draft: 0, submitted: 0, approved: 0, rejected: 0 };
  for (const r of rows) counts[r.status] = (counts[r.status] ?? 0) + 1;
  return counts;
}
