/** Small pure helpers for the operator console's screens. */

export type UnitStatus = "available" | "installed" | "needs_upgrade";
export type UnitAction = "install" | "upgrade" | "uninstall";

/** Which actions a unit's status offers. The kernel can never be uninstalled; the server re-checks everything. */
export function actionsFor(unit: { status: string; kind: string }): UnitAction[] {
  if (unit.status === "available") return ["install"];
  const actions: UnitAction[] = [];
  if (unit.status === "needs_upgrade") actions.push("upgrade");
  if (unit.kind !== "kernel") actions.push("uninstall");
  return actions;
}

export const STATUS_TONE: Record<string, "ok" | "warn" | "neutral"> = { installed: "ok", needs_upgrade: "warn", available: "neutral" };

/** "3 min", "5 h", "2 d": how long ago, from a number of seconds. */
export function ageLabel(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "-";
  if (seconds < 90) return `${Math.max(0, Math.round(seconds))} s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)} h`;
  return `${Math.round(seconds / 86400)} d`;
}

/** A backup is "fresh" under 26 hours (nightly, with a little slack), "old" otherwise. */
export function backupTone(hours: number | null | undefined): "ok" | "warn" | "bad" {
  if (hours === null || hours === undefined) return "bad";
  return hours <= 26 ? "ok" : hours <= 72 ? "warn" : "bad";
}

/** A reason is long enough to mean something (the server holds the same rule). */
export const MIN_REASON = 5;
export const reasonOk = (reason: string, minimum = MIN_REASON): boolean => reason.trim().length >= minimum;

/** The units named in an install plan, in the order they will be installed (what the unit requires first). */
export function installList(plan: { will_install: { title: string }[] }): string {
  return plan.will_install.map((u) => u.title).join(", ");
}
