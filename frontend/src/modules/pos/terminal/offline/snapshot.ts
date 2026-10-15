/** "Network first, then what we kept": data the terminal needs to start, with a copy on the device for when there is no connection. */
import { isOnline, isUnreachable, reportReachable } from "./connectivity";
import { kvDelete, kvGet, kvSet } from "./idb";

export interface Snapshot<T> {
  data: T;
  /** True when the server could not be reached and this is the copy kept earlier. */
  fromCache: boolean;
  savedAt: number;
}

interface Saved<T> {
  data: T;
  savedAt: number;
}

async function saved<T>(key: string): Promise<Saved<T> | undefined> {
  try {
    return await kvGet<Saved<T>>(key);
  } catch {
    return undefined;
  }
}

export async function networkFirst<T>(key: string, fetcher: () => Promise<T>): Promise<Snapshot<T>> {
  // Already known to be offline: do not wait for a request to fail when a copy is there.
  if (!isOnline()) {
    const copy = await saved<T>(key);
    if (copy) return { ...copy, fromCache: true };
  }
  try {
    const data = await fetcher();
    reportReachable(true);
    const savedAt = Date.now();
    void kvSet(key, { data, savedAt }).catch(() => undefined);
    return { data, fromCache: false, savedAt };
  } catch (error) {
    if (!isUnreachable(error)) throw error;
    reportReachable(false);
    const copy = await saved<T>(key);
    if (copy) return { ...copy, fromCache: true };
    throw error;
  }
}

export const forgetSnapshot = (key: string): Promise<void> => kvDelete(key).catch(() => undefined);
export const orgKey = (userId: string): string => `orgs:${userId}`;
export const branchKey = (userId: string, branchId: string): string => `branch:${userId}:${branchId}`;
