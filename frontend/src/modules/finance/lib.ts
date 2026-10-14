/** Pure helpers for the finance screens (preview totals, account tree). The backend owns the real arithmetic. */

/** Money text to whole hundredths, so a live total never shows floating point noise. */
export function toMinor(value: string): number {
  const v = value.trim();
  if (!v) return 0;
  const n = Number(v);
  return Number.isFinite(n) ? Math.round(n * 100) : 0;
}

export function fromMinor(minor: number): string {
  return (minor / 100).toFixed(2);
}

export interface DraftLine {
  account_id: string;
  debit: string;
  credit: string;
}

export type JournalProblem = "fewLines" | "noAccount" | "bothSides" | "noAmount";

export interface JournalPreview {
  debit: string;
  credit: string;
  /** Debit less credit: zero when the entry balances. */
  difference: string;
  balanced: boolean;
  problems: JournalProblem[];
  /** Balanced, with at least two usable lines and nothing wrong: safe to save. */
  ready: boolean;
}

/** Live totals and what is still wrong with a manual journal, for the form's footer. Blank lines are ignored. */
export function previewJournal(lines: readonly DraftLine[]): JournalPreview {
  let debit = 0;
  let credit = 0;
  let usable = 0;
  const problems = new Set<JournalProblem>();
  for (const l of lines) {
    const d = toMinor(l.debit);
    const c = toMinor(l.credit);
    if (!l.account_id && !d && !c) continue;
    debit += d;
    credit += c;
    if (!l.account_id) problems.add("noAccount");
    else if (d && c) problems.add("bothSides");
    else if (!d && !c) problems.add("noAmount");
    else usable += 1;
  }
  if (usable < 2) problems.add("fewLines");
  const balanced = debit === credit && debit > 0;
  return {
    debit: fromMinor(debit), credit: fromMinor(credit), difference: fromMinor(debit - credit), balanced,
    problems: [...problems], ready: balanced && problems.size === 0,
  };
}

/** True when a decimal string is zero (or empty). */
export const isZero = (value: string | null | undefined): boolean => toMinor(value ?? "") === 0;

interface Node {
  id: string;
  code: string;
  parent_id: string | null;
}

/** The chart in tree order (children under their parent, each level by code) with each row's depth. */
export function orderAccounts<A extends Node>(accounts: readonly A[]): { account: A; depth: number }[] {
  const ids = new Set(accounts.map((a) => a.id));
  const children = new Map<string | null, A[]>();
  for (const a of accounts) {
    const key = a.parent_id && ids.has(a.parent_id) ? a.parent_id : null;
    children.set(key, [...(children.get(key) ?? []), a]);
  }
  const out: { account: A; depth: number }[] = [];
  const visit = (parent: string | null, depth: number) => {
    for (const a of [...(children.get(parent) ?? [])].sort((x, y) => x.code.localeCompare(y.code, undefined, { numeric: true }))) {
      out.push({ account: a, depth });
      visit(a.id, depth + 1);
    }
  };
  visit(null, 0);
  return out;
}

/** A signed money amount typed by a person: optional minus, digits, up to two decimals. */
export const isSignedAmount = (value: string): boolean => /^-?\d+(\.\d{1,2})?$/.test(value.trim());
