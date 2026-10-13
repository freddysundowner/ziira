/**
 * Typed API client. Types come from the backend (npm run api), so a backend change that breaks
 * the frontend shows up as a TypeScript error, not a bug in production.
 *
 * The access token lives in memory; the refresh token in localStorage with this browser's device
 * id (the backend binds refresh tokens to the device). On a 401 the client refreshes once and retries.
 */
import createClient, { type Middleware } from "openapi-fetch";

import type { components, paths } from "@/api/schema";

import { readStored, writeStored } from "./storage";

export type Schemas = components["schemas"];

const REFRESH_KEY = "ziira.refresh";
const DEVICE_KEY = "ziira.device";

let accessToken: string | null = null;
let onSignedOut: () => void = () => {};

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

let refreshing: Promise<boolean> | null = null;

/** Swap the stored refresh token for new tokens. False if the session is over. */
export function refreshTokens(): Promise<boolean> {
  const refresh_token = readStored(REFRESH_KEY);
  if (!refresh_token) return Promise.resolve(false);
  refreshing ??= fetch("/api/v1/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token, device_id: deviceId() }),
  })
    .then(async (r) => {
      if (!r.ok) return false;
      const body = (await r.json()) as Schemas["TokensOut"];
      setTokens(body.access_token, body.refresh_token);
      return true;
    })
    .catch(() => false)
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
    if (response.status !== 401 || request.url.includes("/auth/")) return response;
    if (await refreshTokens()) {
      const retry = request.clone();
      retry.headers.set("Authorization", `Bearer ${accessToken}`);
      return fetch(retry);
    }
    setTokens(null, null);
    onSignedOut();
    return response;
  },
};

export const api = createClient<paths>({ baseUrl: "" });
api.use(auth);

/** The error body every backend error uses: { error, message }. */
export function errorMessage(error: unknown): string {
  if (error && typeof error === "object" && "message" in error) return String(error.message);
  if (error && typeof error === "object" && "detail" in error) return "Please check the form.";
  return "Something went wrong. Please try again.";
}
