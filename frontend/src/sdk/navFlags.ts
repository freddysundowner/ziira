/**
 * Small switches and counts the sidebar reads: a module's `shell.background` slot component sets them (a menu entry that
 * appears only when something exists, a count next to an entry). Kept outside React state so any component can set them.
 */
import { useSyncExternalStore } from "react";

let flags: ReadonlySet<string> = new Set();
let badges: Readonly<Record<string, number>> = {};
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

/** Turn a navigation flag on or off. */
export function setNavFlag(name: string, on: boolean): void {
  if (flags.has(name) === on) return;
  const next = new Set(flags);
  if (on) next.add(name); else next.delete(name);
  flags = next;
  emit();
}

/** Show a count next to a sidebar entry (an area id, or a page path); zero hides it. */
export function setNavBadge(key: string, count: number): void {
  if ((badges[key] ?? 0) === count) return;
  badges = { ...badges, [key]: count };
  emit();
}

const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };

export const useNavFlags = (): ReadonlySet<string> => useSyncExternalStore(subscribe, () => flags);
export const useNavBadges = (): Readonly<Record<string, number>> => useSyncExternalStore(subscribe, () => badges);
