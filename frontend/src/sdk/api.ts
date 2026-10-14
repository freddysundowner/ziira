/**
 * Typed API client. Types come from the backend (npm run api), so a backend change that breaks
 * the frontend shows up as a TypeScript error, not a bug in production.
 *
 * The access token lives in memory; the refresh token in localStorage with this browser's device
 * id (the backend binds refresh tokens to the device). On a 401 the client refreshes once and retries.
 */
import createClient, { type Middleware } from "openapi-fetch";

import type { components, paths } from "@/api/schema";

import { isSetupRequired } from "./mfa/helpers";
import { readStored, writeStored } from "./storage";

export type Schemas = components["schemas"];

const REFRESH_KEY = "ziira.refresh";
const DEVICE_KEY = "ziira.device";

let accessToken: string | null = null;
let onSignedOut: () => void = () => {};
let onSetupRequired: () => void = () => {};

/** A stable id for this browser, sent at sign-in and refresh. */
export function deviceId(): string {
  let id = readStored(DEVICE_KEY);
  if (!id) {
    id = crypto.randomUUID();
    writeStored(DEVICE_KEY, id);
  }
  return id;
}

export function setTokens(access: string | null, refresh?: string | null): void {
  accessToken = access;
  if (refresh !== undefined) writeStored(REFRESH_KEY, refresh);
}

export function hasRefreshToken(): boolean {
  return readStored(REFRESH_KEY) !== null;
}

export function whenSignedOut(callback: () => void): void {
  onSignedOut = callback;
}

/** Called when any request is answered "set up two-step verification first" (the business now requires it of this person). */
export function whenSetupRequired(callback: () => void): void {
  onSetupRequired = callback;
}

let refreshing: Promise<Refresh> | null = null;

/** "ok": new tokens. "denied": the session is over (sign in again). "offline": we could not ask, so keep the session and try later. */
export type Refresh = "ok" | "denied" | "offline";

/** Swap the stored refresh token for new tokens. */
export function refreshTokens(): Promise<Refresh> {
  const refresh_token = readStored(REFRESH_KEY);
  if (!refresh_token) return Promise.resolve("denied");
  refreshing ??= fetch("/api/v1/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token, device_id: deviceId() }),
  })
    .then(async (r): Promise<Refresh> => {
      if (r.status === 401 || r.status === 403 || r.status === 422) return "denied";
      if (!r.ok) return "offline";
      const body = (await r.json()) as Schemas["TokensOut"];
      setTokens(body.access_token, body.refresh_token);
      return "ok";
    })
    .catch((): Refresh => "offline")
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

const auth: Middleware = {
  onRequest({ request }) {
    if (accessToken) request.headers.set("Authorization", `Bearer ${accessToken}`);
    return request;
  },
  async onResponse({ request, response }) {
    if (response.status === 403 && !request.url.includes("/auth/")) {
      const body: unknown = await response.clone().json().catch(() => null);
      if (isSetupRequired(response.status, body)) onSetupRequired();
      return response;
    }
    if (response.status !== 401 || request.url.includes("/auth/")) return response;
    const result = await refreshTokens();
    if (result === "ok") {
      const retry = request.clone();
      retry.headers.set("Authorization", `Bearer ${accessToken}`);
      return fetch(retry);
    }
    if (result === "denied") {
      setTokens(null, null);
      onSignedOut();
    }
    return response;
  },
};

/** A request that could not reach the server becomes a 503 with a readable message, so callers handle one shape. */
const network: Middleware = {
  onError() {
    return new Response(JSON.stringify({ error: "network", message: "Cannot reach the server. Check your connection and try again." }), {
      status: 503,
      headers: { "Content-Type": "application/json" },
    });
  },
};

export const api = createClient<paths>({ baseUrl: "" });
api.use(auth);
api.use(network);

/** An API failure with what a screen needs: a message for people, the status, and per-field messages when the form was invalid. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly fields: Record<string, string> = {},
  ) {
    super(message);
  }
}

/** Per-field messages from a FastAPI validation error (422): { "body.name": "Field required" }. */
function fieldErrors(error: unknown): Record<string, string> {
  const out: Record<string, string> = {};
  const detail = (error as { detail?: unknown } | null)?.detail;
  if (!Array.isArray(detail)) return out;
  for (const item of detail as { loc?: unknown[]; msg?: string }[]) {
    const path = (item.loc ?? []).filter((p) => p !== "body" && p !== "query").join(".");
    if (path && item.msg) out[path] = item.msg;
  }
  return out;
}

/**
 * Turn an openapi-fetch result into its data, or throw an ApiError. Use it in every query and mutation so a failed
 * request is an error state (with retry), never an empty list.
 */
export async function unwrap<T>(request: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await request;
  if (response.ok) return data as T;
  throw new ApiError(errorMessage(error, response.status), response.status, fieldErrors(error));
}

/** The error body every backend error uses: { error, message }. */
export function errorMessage(error: unknown, status?: number): string {
  if (error instanceof Error && !(error instanceof ApiError) && error.message) return error.message;
  if (error instanceof ApiError) return error.message;
  if (error && typeof error === "object" && "message" in error && error.message) return String(error.message);
  if (error && typeof error === "object" && "detail" in error) {
    const fields = Object.entries(fieldErrors(error));
    return fields.length ? fields.map(([f, m]) => `${f.replace(/_/g, " ")}: ${m}`).join(" · ") : "Please check the form.";
  }
  if (status === 403) return "You do not have permission to do that.";
  if (status === 404) return "That could not be found.";
  if (status && status >= 500) return "The server had a problem. Please try again.";
  return "Something went wrong. Please try again.";
}
