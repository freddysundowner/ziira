import { useState } from "react";

/** Rows of a document being typed. Each row has a stable `key` so editing one never disturbs another. */
export function useLines<T extends { key: string }>(blank: () => Omit<T, "key">, initial: T[] = []) {
  const [lines, setLines] = useState<T[]>(initial);
  const add = (extra?: Partial<T>) => setLines((l) => [...l, { ...blank(), ...extra, key: crypto.randomUUID() } as T]);
  const update = (key: string, patch: Partial<T>) => setLines((l) => l.map((x) => (x.key === key ? { ...x, ...patch } : x)));
  const remove = (key: string) => setLines((l) => l.filter((x) => x.key !== key));
  return { lines, setLines, add, update, remove };
}

/** Layout for one line of a document: stacked on a phone, one row from `md`. */
export const LINE_ROW = "grid gap-3 rounded-lg border border-line bg-sunken/40 p-3 md:items-end";
