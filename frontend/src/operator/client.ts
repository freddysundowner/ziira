/**
 * The operator console's API client. Platform staff sign in with an operator token that is a different kind from a
 * business user's: it is kept here (in memory, and in this tab's session storage so a reload keeps the sign-in), never
 * in the business app's storage, and it is sent only with the console's own requests. It is not refreshed: when it
 * ends (its lifetime, or the idle limit when staff sign in with a password alone), the person signs in again.
 */
import createClient, { type Middleware } from "openapi-fetch";

import type { paths } from "@/api/schema";
import { ApiError, errorMessage } from "@/sdk";

const KEY = "ziira.operator.token";

let token: string | null = readToken();
let onEnded: () => void = () => {};

function readToken(): string | null {
  try {
    return sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function setOperatorToken(value: string | null): void {
  token = value;
  try {
    if (value) sessionStorage.setItem(KEY, value);
    else sessionStorage.removeItem(KEY);
  } catch {
    // not remembered across a reload; the sign-in still works
  }
}

export const hasOperatorToken = (): boolean => token !== null;

/** Called when the API says the operator's sign-in is over (401 on a request that was sent with a token). */
export function whenOperatorSessionEnds(callback: () => void): void {
  onEnded = callback;
}

const auth: Middleware = {
  onRequest({ request }) {
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
  onResponse({ request, response }) {
    // A wrong password or code on these is a typing mistake, not the end of the sign-in.
    const answersWrongInput = /\/operator\/(sign-in|mfa\/verify|mfa\/confirm|confirm|password)$/.test(new URL(request.url).pathname);
    if (response.status === 401 && token && !answersWrongInput) {
      setOperatorToken(null);
      onEnded();
    }
    return response;
  },
};

const network: Middleware = {
  onError() {
    return new Response(JSON.stringify({ error: "network", message: "Cannot reach the server. Check your connection and try again." }), {
      status: 503,
      headers: { "Content-Type": "application/json" },
    });
  },
};

export const opApi = createClient<paths>({ baseUrl: "" });
opApi.use(auth);
opApi.use(network);

/** An API failure that also carries the server's error code and any extra fields (the businesses that block an uninstall ...). */
export class OperatorApiError extends ApiError {
  constructor(message: string, status: number, readonly code: string, readonly body: Record<string, unknown>) {
    super(message, status);
  }
}

/** The server's code (kept from the days of authenticator codes) for "confirm again before this change". */
export const STEP_UP_CODE = "mfa_step_up_required";
export const PASSWORD_CHANGE_CODE = "password_change_required"; // secret-scan: ignore (an error code, not a secret)

export function isStepUp(error: unknown): boolean {
  return error instanceof OperatorApiError && error.status === 403 && error.code === STEP_UP_CODE;
}

/** Like `unwrap` in the SDK, but keeps the error code and body so screens can react to them. */
export async function opUnwrap<T>(request: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await request;
  if (response.ok) return data as T;
  const body = (error && typeof error === "object" ? error : {}) as Record<string, unknown>;
  throw new OperatorApiError(errorMessage(error, response.status), response.status, typeof body.error === "string" ? body.error : "", body);
}

/**
 * Fetches a file the console shows or saves (an export, a printable invoice) with the operator's token, as a blob.
 * Failures read like any other request's: the server's message, with its code.
 */
export async function opDownload(path: string): Promise<Blob> {
  let response: Response;
  try {
    response = await fetch(new Request(path, { headers: token ? { Authorization: `Bearer ${token}` } : {} }));
  } catch {
    throw new OperatorApiError("Cannot reach the server. Check your connection and try again.", 503, "network", {});
  }
  if (response.status === 401 && token) {
    setOperatorToken(null);
    onEnded();
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as Record<string, unknown>;
    throw new OperatorApiError(errorMessage(body, response.status), response.status, typeof body.error === "string" ? body.error : "", body);
  }
  return response.blob();
}

/** Hands a blob to the browser as a download. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/** Saves text (a licence file, a revocation list) under a file name. */
export const saveText = (content: string, filename: string): void => saveBlob(new Blob([content], { type: "text/plain" }), filename);
