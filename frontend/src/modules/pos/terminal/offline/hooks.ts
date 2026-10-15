import { useEffect, useSyncExternalStore } from "react";

import { count, chipOf, outboxWarnings, reservedQuantities } from "./outbox";
import { getOutboxState, startOutbox, subscribeOutbox } from "./controller";
import { isOnline, subscribeConnectivity } from "./connectivity";

/** True while the terminal can reach the server. */
export function useOnline(): boolean {
  return useSyncExternalStore(subscribeConnectivity, isOnline, () => true);
}

/** The outbox, live. Starting it (reading the disk, sending what is waiting) happens once, the first time a screen asks. */
export function useOutbox() {
  useEffect(() => startOutbox(), []);
  const state = useSyncExternalStore(subscribeOutbox, getOutboxState, getOutboxState);
  const online = useOnline();
  const counts = count(state.entries);
  return {
    ...state,
    online,
    counts,
    chip: chipOf(counts, online),
    warnings: outboxWarnings(state.entries, Date.now()),
    reserved: (branchId: string) => reservedQuantities(state.entries, branchId),
  };
}
