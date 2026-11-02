import { useSyncExternalStore } from "react";

import { readStored, writeStored } from "@/sdk";

const KEY = "ziira.memberships.more";
const listeners = new Set<() => void>();
let on = readStored(KEY) === "1";

/** Whether the owner switched on the extra gym tools (reports, recurring invoices, extras). Remembered on this device. */
export function setMoreTools(next: boolean): void {
  on = next;
  writeStored(KEY, next ? "1" : "0");
  listeners.forEach((l) => l());
}

export const useMoreTools = (): boolean =>
  useSyncExternalStore((l) => { listeners.add(l); return () => { listeners.delete(l); }; }, () => on);
