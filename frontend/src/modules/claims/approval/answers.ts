/** The payer's answers on the response page, kept as plain data so they can be checked and tested without the page. */
import { cents } from "../lib";
import type { AnswerBody, PublicLine } from "./api";

export interface Pick { state: "" | "approved" | "countered" | "rejected" | "needs_information"; amount: string; reason: string }
export const EMPTY_PICK: Pick = { state: "", amount: "", reason: "" };

/** The lines the payer still has to answer: not settled earlier and not already answered. */
export const openLines = (lines: readonly PublicLine[]) => lines.filter((l) => !l.locked && (l.state === "pending" || l.state === "needs_information"));

export type PickProblem = "state" | "amount" | "reason";

export function pickProblem(pick: Pick, total: string): PickProblem | null {
  if (!pick.state) return "state";
  if (pick.state === "countered") {
    const a = cents(pick.amount);
    if (!pick.amount.trim() || a < 0 || a >= cents(total)) return "amount";
  }
  if (pick.state === "rejected" && !pick.reason.trim()) return "reason";
  return null;
}

/** Everything that stops the payer from signing off: a line without an answer, a bad counter-offer, a rejection without its reason, no name. */
export function signOffProblems(lines: readonly PublicLine[], picks: Record<string, Pick>, name: string): { lines: Record<string, PickProblem>; name: boolean } {
  const found: Record<string, PickProblem> = {};
  for (const l of openLines(lines)) {
    const p = pickProblem(picks[l.id] ?? EMPTY_PICK, l.total);
    if (p) found[l.id] = p;
  }
  return { lines: found, name: !name.trim() };
}

export function toBody(lines: readonly PublicLine[], picks: Record<string, Pick>, who: { name: string; role: string; note: string; authority: string; authorityAmount: string }): AnswerBody {
  return {
    name: who.name.trim(), role: who.role.trim() || null, note: who.note.trim() || null,
    authority_ref: who.authority.trim() || null, authority_amount: who.authorityAmount.trim() || null,
    lines: openLines(lines).map((l) => {
      const p = picks[l.id] ?? EMPTY_PICK;
      return { line_id: l.id, state: p.state as "approved", amount: p.state === "countered" ? p.amount.trim() : null, reason: p.reason.trim() || null };
    }),
  };
}
