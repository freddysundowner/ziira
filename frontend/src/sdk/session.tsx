/**
 * The signed-in session: who the user is, what they may do, and which units the business enabled.
 */
import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api, deviceId, errorMessage, hasRefreshToken, refreshTokens, type Schemas, setTokens, whenSetupRequired, whenSignedOut } from "./api";

import { classifyVerifyFailure, isSetupRequired, retryAfterSeconds } from "./mfa/helpers";
import { readStored, writeStored } from "./storage";

type Me = Schemas["MeOut"];

/** The fields of the API's error body that sign-in cares about. */
interface SignInErrorBody {
  error?: string;
  challenge?: string;
  businesses?: Business[];
}

export interface Session {
  /** "mfa-setup": signed in, but the business requires two-step verification and this person has not set it up yet. */
  status: "loading" | "signed-out" | "signed-in" | "unreachable" | "mfa-setup";
  me: Me | null;
  enabledUnits: ReadonlySet<string>;
  /** True if the user holds the permission in at least one scope. The backend checks scope. */
  can: (permission: string) => boolean;
  /** Signs in with a login and password. If the same login works for several businesses, says which (the caller asks
   *  again with the chosen workspace code). If the person uses a second factor, returns a `mfaChallenge` to complete with `completeMfa`. */
  signIn: (login: string, password: string, workspace?: string) => Promise<SignInResult>;
  /** The second step of signing in: the challenge from `signIn` and a code from the authenticator app (or a backup code). */
  completeMfa: (challenge: string, code: string) => Promise<SignInResult>;
  signOut: () => Promise<void>;
  /** Tries again after the server could not be reached. */
  retry: () => void;
  /** Re-reads who the user is, their permissions and the enabled units, without signing out (after Add-ons changed). */
  refresh: () => Promise<void>;
  /** Asks for a business of your own; the person must then use the link emailed to them. */
  register: (input: RegisterInput) => Promise<RegisterResult>;
  /** Uses the emailed link: creates the business and signs the owner in. `error` is null on success. */
  completeRegistration: (token: string) => Promise<RegistrationCompletion>;
}

export interface RegisterResult {
  error: string | null;
  devToken?: string;
  /** Present when the platform has no working email: go to /register/verify with it at once, no email is sent. */
  instantToken?: string;
  /** HTTP status of a failure (422 invalid, 429 too many, 503 unavailable). */
  status?: number;
  /** The server's error code (`validation_failed`, `too_many_requests`, ...). */
  code?: string;
  /** Messages per field of the request (`email`, `password` ...) from a 422. */
  fields?: Record<string, string>;
  /** Seconds to wait after a 429. */
  retryAfter?: number;
}

export interface RegistrationCompletion {
  error: string | null;
  status?: number;
  code?: string;
  retryAfter?: number;
  /** The id to quote to support. */
  requestId?: string;
}

export interface RegisterInput {
  business_name: string;
  owner_name: string;
  email: string;
  password: string;
  country: string;
  currency: string;
  phone_country_code: string;
  timezone?: string;
  tax_id?: string;
  invite_code?: string;
  /** What the business needs: retail, distribution, books, intelligence or full (the default). */
  edition?: string;
  /** Onboarding answers (hints only). */
  phone?: string;
  owner_role?: string;
  business_size?: string;
  staff_size?: string;
  business_type?: string;
  /** A public plan code from a website link (unknown ones are ignored). */
  plan?: string;
}

export interface Business {
  workspace: string;
  name: string;
}

export interface SignInResult {
  error: string | null;
  businesses?: Business[];
  /** The password was right and a code is needed: send it back with `completeMfa`. Valid for 5 minutes. */
  mfaChallenge?: string;
  /** Too many tries: seconds to wait. */
  retryAfter?: number;
  /** Why a second-factor attempt failed (the wording is in `error`). */
  failure?: "wrong" | "expired" | "throttled" | "other";
}

const SessionContext = createContext<Session | null>(null);

/**
 * Who is signed in and what they may do, kept on this device. When the server cannot be reached (a page loaded without a
 * connection) the session starts from this copy, so the till terminal can open and sell offline; the first request after
 * the connection returns refreshes the tokens as usual. Removed when the session ends.
 */
const SNAPSHOT_KEY = "ziira.session";
function readSnapshot(): { me: Me; units: string[] } | null {
  try {
    const raw = readStored(SNAPSHOT_KEY);
    const parsed = raw ? (JSON.parse(raw) as { me?: Me; units?: string[] }) : null;
    return parsed?.me && Array.isArray(parsed.units) ? { me: parsed.me, units: parsed.units } : null;
  } catch {
    return null;
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Session["status"]>("loading");
  const [me, setMe] = useState<Me | null>(null);
  const [units, setUnits] = useState<ReadonlySet<string>>(new Set());

  /** Start from the copy kept on this device (no connection). False when there is none. */
  const startFromSnapshot = useCallback((): boolean => {
    const saved = readSnapshot();
    if (!saved) return false;
    setMe(saved.me);
    setUnits(new Set(saved.units));
    setStatus("signed-in");
    return true;
  }, []);

  const load = useCallback(async () => {
    const [meResult, unitsResult] = await Promise.all([api.GET("/api/v1/auth/me"), api.GET("/api/v1/units")]);
    if (isSetupRequired(unitsResult.response.status, unitsResult.error)) {
      setStatus("mfa-setup");          // a limited session: only the setup screen may work until it is done
      return;
    }
    if (!meResult.data || !unitsResult.data) {
      // 401/403: the session is over. Anything else (server down, no network): keep the session and let the person retry.
      const failed = !meResult.data ? meResult.response : unitsResult.response;
      if (failed.status === 401 || failed.status === 403) {
        writeStored(SNAPSHOT_KEY, null);
        setStatus("signed-out");
      } else if (!startFromSnapshot()) setStatus("unreachable");
      return;
    }
    const enabled = unitsResult.data.filter((u) => u.enabled).map((u) => String(u.name));
    writeStored(SNAPSHOT_KEY, JSON.stringify({ me: meResult.data, units: enabled }));
    setMe(meResult.data);
    setUnits(new Set(enabled));
    setStatus("signed-in");
  }, [startFromSnapshot]);

  const start = useCallback(async () => {
    if (!hasRefreshToken()) {
      setStatus("signed-out");
      return;
    }
    setStatus("loading");
    const result = await refreshTokens();
    if (result === "ok") await load();
    else if (result === "denied") {
      writeStored(SNAPSHOT_KEY, null);
      setStatus("signed-out");
    } else if (!startFromSnapshot()) setStatus("unreachable");
  }, [load, startFromSnapshot]);

  useEffect(() => {
    whenSignedOut(() => { writeStored(SNAPSHOT_KEY, null); setStatus("signed-out"); });
    whenSetupRequired(() => setStatus("mfa-setup"));
    void start();
  }, [start]);

  const signIn = useCallback(
    async (login: string, password: string, workspace?: string): Promise<SignInResult> => {
      const { data, error, response } = await api.POST("/api/v1/auth/sign-in", {
        body: { workspace: workspace ?? null, login, password, device_id: deviceId(), device_name: navigator.userAgent.slice(0, 60), channel: "web" },
      });
      if (!data) {
        const body = error as SignInErrorBody | undefined;
        if (response.status === 401 && body?.error === "mfa_required" && body.challenge) return { error: null, mfaChallenge: body.challenge };
        if (response.status === 429) return { error: errorMessage(error), retryAfter: retryAfterSeconds(error, response.headers.get("Retry-After")) };
        return body?.businesses?.length ? { error: null, businesses: body.businesses } : { error: errorMessage(error) };
      }
      setTokens(data.access_token, data.refresh_token);
      await load();
      return { error: null };
    },
    [load],
  );

  const completeMfa = useCallback(
    async (challenge: string, code: string): Promise<SignInResult> => {
      const { data, error, response } = await api.POST("/api/v1/auth/mfa/verify", { body: { challenge, code } });
      if (!data) {
        const failure = classifyVerifyFailure(response.status, error, response.headers.get("Retry-After"));
        return { error: errorMessage(error), failure: failure.kind, retryAfter: failure.kind === "throttled" ? failure.retryAfter : undefined };
      }
      setTokens(data.access_token, data.refresh_token);
      await load();
      return { error: null };
    },
    [load],
  );

  const register = useCallback(async (input: RegisterInput): Promise<RegisterResult> => {
    const { data, error, response } = await api.POST("/api/v1/register", {
      body: { ...input, invite_code: input.invite_code || null, edition: input.edition ?? "full" },
    });
    if (response.ok) return { error: null, devToken: data?.dev_token ?? undefined, instantToken: data?.instant_token ?? undefined };
    const body = error as { error?: string; message?: string; field?: string; detail?: { loc?: unknown[]; msg?: string }[] } | undefined;
    const fields: Record<string, string> = {};
    if (body?.field && body.message) fields[body.field] = body.message;
    for (const item of Array.isArray(body?.detail) ? body.detail : []) {
      const name = String(item.loc?.[item.loc.length - 1] ?? "");
      if (name && item.msg) fields[name] = item.msg;
    }
    return {
      error: errorMessage(error), status: response.status, code: body?.error, fields,
      retryAfter: response.status === 429 ? retryAfterSeconds(error, response.headers.get("Retry-After")) : undefined,
    };
  }, []);

  const completeRegistration = useCallback(
    async (token: string): Promise<RegistrationCompletion> => {
      const { data, error, response } = await api.POST("/api/v1/register/verify", {
        body: { token, device_id: deviceId(), device_name: navigator.userAgent.slice(0, 60) },
      });
      if (!data) {
        const body = error as { error?: string; request_id?: string } | undefined;
        return {
          error: errorMessage(error), status: response.status, code: body?.error, requestId: body?.request_id,
          retryAfter: response.status === 429 ? retryAfterSeconds(error, response.headers.get("Retry-After")) : undefined,
        };
      }
      setTokens(data.access_token, data.refresh_token);
      await load();
      return { error: null };
    },
    [load],
  );

  const signOut = useCallback(async () => {
    await api.POST("/api/v1/auth/sign-out").catch(() => undefined);
    setTokens(null, null);
    writeStored(SNAPSHOT_KEY, null);
    setMe(null);
    setStatus("signed-out");
  }, []);

  const value = useMemo<Session>(() => {
    const permissions = new Set(me?.roles.flatMap((r) => r.permissions) ?? []);
    return { status, me, enabledUnits: units, can: (p) => permissions.has(p), signIn, completeMfa, signOut, register, completeRegistration, retry: () => void start(), refresh: load };
  }, [status, me, units, signIn, completeMfa, signOut, register, completeRegistration, start, load]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession must be used inside SessionProvider");
  return session;
}

/** Shortcut: does the signed-in user hold this permission? */
export function useCan(permission: string): boolean {
  return useSession().can(permission);
}
