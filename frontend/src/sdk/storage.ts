/**
 * Browser storage that never crashes: storage can be missing or blocked (private windows,
 * strict settings, tests). Then values simply are not remembered.
 */
function store(): Storage | null {
  try {
    return typeof localStorage !== "undefined" && localStorage ? localStorage : null;
  } catch {
    return null;
  }
}

export function readStored(key: string): string | null {
  try {
    return store()?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

export function writeStored(key: string, value: string | null): void {
  try {
    if (value === null) store()?.removeItem(key);
    else store()?.setItem(key, value);
  } catch {
    // not remembered; nothing else to do
  }
}
