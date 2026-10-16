/**
 * Editions on the web: the business's edition (a named bundle of units) shapes the menu order, the page opened after
 * sign-in and the first-steps checklist. Pure rules here (tested); `useEdition` reads the server.
 */
import { useQuery } from "@tanstack/react-query";

import { api, type Schemas, unwrap } from "./api";
import { MENU_GROUPS, type MenuGroup } from "./module";

export type Edition = Schemas["EditionOut"];
export type EditionStep = Schemas["StepOut"];
export type MyEdition = Schemas["MyEditionOut"];

export const EDITION_KEY = ["edition"];
const LANDED_KEY = "ziira.landed";

/** The business's edition and first-steps progress. Absent (undefined) while loading or if it cannot be read: the app then behaves as the full edition. */
export function useEdition() {
  const query = useQuery({ queryKey: EDITION_KEY, queryFn: () => unwrap(api.GET("/api/v1/edition")), staleTime: 60_000 });
  return { mine: query.data, edition: query.data?.edition, isLoading: query.isLoading, refetch: query.refetch };
}

/** The editions a new business can choose from (public: the sign-up form uses it). */
export function useEditionChoices() {
  return useQuery({ queryKey: ["editions"], queryFn: () => unwrap(api.GET("/api/v1/editions")), staleTime: 10 * 60_000 });
}

/** Sidebar sections: the edition's own order first, the others after in the usual order. */
export function orderedGroups(edition: Pick<Edition, "menu_groups"> | undefined): MenuGroup[] {
  const own = (edition?.menu_groups ?? []).filter((g): g is MenuGroup => (MENU_GROUPS as readonly string[]).includes(g));
  return [...own, ...MENU_GROUPS.filter((g) => !own.includes(g))];
}

/** First steps worth showing: those whose unit is on (a step with no unit always shows). */
export function visibleSteps(edition: Pick<Edition, "checklist">, enabledUnits: ReadonlySet<string>): EditionStep[] {
  return edition.checklist.filter((s) => !s.unit || enabledUnits.has(s.unit));
}

export function progress(steps: readonly EditionStep[], done: readonly string[]): { done: number; total: number; complete: boolean } {
  const finished = steps.filter((s) => done.includes(s.id)).length;
  return { done: finished, total: steps.length, complete: steps.length > 0 && finished === steps.length };
}

/** Where to send a person right after sign-in: the edition's landing page, once per browser session, if they may open it. */
export function landingTarget(landing: string | undefined, openable: ReadonlySet<string>, alreadyLanded: boolean): string | null {
  return !alreadyLanded && landing && openable.has(landing) ? landing : null;
}

export function hasLanded(): boolean {
  try { return sessionStorage.getItem(LANDED_KEY) === "1"; } catch { return true; }
}

export function setLanded(): void {
  try { sessionStorage.setItem(LANDED_KEY, "1"); } catch { /* not remembered: the landing page may open once more */ }
}
