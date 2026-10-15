/**
 * Are we connected? The browser's online flag is only a hint (a router with no internet still says "online"), so the
 * terminal also notes whether its own requests got an answer. While it believes it is offline it checks the server
 * every few seconds, so selling returns to normal on its own.
 */
import { api, ApiError } from "@/sdk";

type Listener = () => void;

const state = { browserOnline: typeof navigator === "undefined" || navigator.onLine, reachable: true };
const listeners = new Set<Listener>();
let installed = false;
let probeTimer: number | undefined;
export const PROBE_EVERY_MS = 8_000;

const emit = () => listeners.forEach((l) => l());
export const isOnline = (): boolean => state.browserOnline && state.reachable;

/** Failed for lack of a connection or because the server is not answering (not because it refused). */
export function isUnreachable(error: unknown): boolean {
  if (error instanceof ApiError) return [0, 502, 503, 504].includes(error.status);
  return error instanceof TypeError;
}

export function reportReachable(ok: boolean): void {
  if (state.reachable === ok) return;
  state.reachable = ok;
  if (ok) stopProbe();
  else startProbe();
  emit();
}

/** Await a request and note whether the server answered. */
export async function tracked<T>(request: Promise<T>): Promise<T> {
  try {
    const value = await request;
    reportReachable(true);
    return value;
  } catch (error) {
    if (isUnreachable(error)) reportReachable(false);
    else reportReachable(true);
    throw error;
  }
}

/** Await an API call and note whether the server answered (the web layer turns "no connection" into a 503 answer). */
export async function trackedApi<T extends { response: Response }>(request: Promise<T>): Promise<T> {
  try {
    const result = await request;
    reportReachable(![502, 503, 504].includes(result.response.status));
    return result;
  } catch (error) {
    reportReachable(!isUnreachable(error));
    throw error;
  }
}

async function probe(): Promise<void> {
  try {
    // Any answer, even "sign in first", proves the server is there.
    const { response } = await api.GET("/api/v1/units");
    reportReachable(![502, 503, 504].includes(response.status));
  } catch {
    reportReachable(false);
  }
}

function startProbe(): void {
  if (probeTimer !== undefined || typeof window === "undefined") return;
  probeTimer = window.setInterval(() => { if (state.browserOnline) void probe(); }, PROBE_EVERY_MS);
}
function stopProbe(): void {
  if (probeTimer !== undefined) window.clearInterval(probeTimer);
  probeTimer = undefined;
}

function install(): void {
  if (installed || typeof window === "undefined") return;
  installed = true;
  window.addEventListener("online", () => { state.browserOnline = true; emit(); void probe(); });
  window.addEventListener("offline", () => { state.browserOnline = false; emit(); });
  if (!state.browserOnline) startProbe();
}

export function subscribeConnectivity(listener: Listener): () => void {
  install();
  listeners.add(listener);
  return () => listeners.delete(listener);
}
