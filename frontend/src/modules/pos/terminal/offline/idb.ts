/**
 * A very small wrapper over IndexedDB (no library). One database, two stores:
 *   kv      small named values: the copy of prices and customers, counters, the clock offset
 *   outbox  the sales made without a connection, keyed by their client-made id
 * Every function rejects when the browser cannot store (private windows, blocked storage, a full disk): callers say so
 * and refuse to sell offline instead of pretending.
 */
const DB_NAME = "ziira-pos";
const DB_VERSION = 1;
export const KV = "kv";
export const OUTBOX = "outbox";

export class StorageUnavailable extends Error {
  constructor(message = "This browser cannot keep data on this device.") {
    super(message);
  }
}

let opening: Promise<IDBDatabase> | null = null;

export function openDb(): Promise<IDBDatabase> {
  if (opening) return opening;
  opening = new Promise<IDBDatabase>((resolve, reject) => {
    if (typeof indexedDB === "undefined") { reject(new StorageUnavailable()); return; }
    let request: IDBOpenDBRequest;
    try {
      request = indexedDB.open(DB_NAME, DB_VERSION);
    } catch (error) {
      reject(new StorageUnavailable((error as Error).message));
      return;
    }
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(KV)) db.createObjectStore(KV);
      if (!db.objectStoreNames.contains(OUTBOX)) db.createObjectStore(OUTBOX, { keyPath: "localId" });
    };
    request.onsuccess = () => {
      const db = request.result;
      db.onclose = () => { opening = null; };
      db.onversionchange = () => { db.close(); opening = null; };
      resolve(db);
    };
    request.onerror = () => reject(new StorageUnavailable(request.error?.message));
    request.onblocked = () => reject(new StorageUnavailable("The database is open in an older tab. Close it and reload."));
  }).catch((error) => {
    opening = null;
    throw error;
  });
  return opening;
}

const asPromise = <T>(request: IDBRequest<T>): Promise<T> =>
  new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("Storage request failed"));
  });

/** Run `work` in one transaction over the stores; resolves when the transaction has committed (the data is durable). */
export async function transact<T>(stores: string[], mode: IDBTransactionMode, work: (tx: IDBTransaction) => Promise<T>): Promise<T> {
  const db = await openDb();
  return new Promise<T>((resolve, reject) => {
    let tx: IDBTransaction;
    try {
      tx = db.transaction(stores, mode);
    } catch (error) {
      reject(error);
      return;
    }
    let result: T;
    tx.oncomplete = () => resolve(result);
    tx.onerror = () => reject(tx.error ?? new Error("Storage transaction failed"));
    tx.onabort = () => reject(tx.error ?? new Error("Storage transaction was cancelled"));
    work(tx).then((value) => { result = value; }, (error) => { reject(error); try { tx.abort(); } catch { /* already finished */ } });
  });
}

export async function kvGet<T>(key: string): Promise<T | undefined> {
  return transact([KV], "readonly", (tx) => asPromise<T | undefined>(tx.objectStore(KV).get(key)));
}

export async function kvSet(key: string, value: unknown): Promise<void> {
  await transact([KV], "readwrite", async (tx) => { await asPromise(tx.objectStore(KV).put(value, key)); });
}

export async function kvDelete(key: string): Promise<void> {
  await transact([KV], "readwrite", async (tx) => { await asPromise(tx.objectStore(KV).delete(key)); });
}

export const requestOf = asPromise;

/** Can this browser really store? Writes, reads back and deletes a value. */
export async function probeStorage(): Promise<boolean> {
  try {
    const key = "probe";
    const value = String(Date.now());
    await kvSet(key, value);
    const back = await kvGet<string>(key);
    await kvDelete(key);
    return back === value;
  } catch {
    return false;
  }
}
