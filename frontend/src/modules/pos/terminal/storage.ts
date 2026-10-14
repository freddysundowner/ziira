/** Browser storage that never throws: the cart is kept here so a refresh, a crash or a dead connection cannot lose it. */
export function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

export function writeJson(key: string, value: unknown): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // storage full or blocked: the cart still works in memory
  }
}

export function readText(key: string): string {
  try {
    return localStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

export function writeText(key: string, value: string): void {
  writeJson(key, value === "" ? null : value);
}
