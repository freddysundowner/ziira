export interface SetupItem {
  key: string;
  done: boolean;
  to: string;
  needs: string;
  optional: boolean;
  detail: string | null;
  feature: string | null;
}

/** The steps this deployment has: the Website step goes when the deployment has no marketing site. */
export function visibleSteps<T extends { feature: string | null }>(items: readonly T[], missingFeatures: readonly string[]): T[] {
  return items.filter((i) => !(i.feature && missingFeatures.includes(i.feature)));
}

/** How far the required steps are: done, total, and whether the owner is finished (optional steps never hold it back). */
export function setupProgress(items: readonly { done: boolean; optional: boolean }[]): { done: number; total: number; complete: boolean } {
  const required = items.filter((i) => !i.optional);
  const done = required.filter((i) => i.done).length;
  return { done, total: required.length, complete: done === required.length };
}

/** The next required step still to do, for the "start here" button. */
export function nextStep<T extends { done: boolean; optional: boolean }>(items: readonly T[]): T | null {
  return items.find((i) => !i.done && !i.optional) ?? null;
}

/** Whether this role may act on the step (otherwise it is listed, read only, with a note). */
export const canAct = (item: { needs: string }, permissions: readonly string[]): boolean => permissions.includes(item.needs);
