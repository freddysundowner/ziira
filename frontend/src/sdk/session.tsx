/**
 * The signed-in session: who the user is, what they may do, and which units the business enabled.
 */
import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api, deviceId, errorMessage, hasRefreshToken, refreshTokens, type Schemas, setTokens, whenSignedOut } from "./api";

type Me = Schemas["MeOut"];

export interface Session {
  status: "loading" | "signed-out" | "signed-in";
  me: Me | null;
  enabledUnits: ReadonlySet<string>;
  /** True if the user holds the permission in at least one scope. The backend checks scope. */
  can: (permission: string) => boolean;
  /** Signs in with a login and password. If the same login works for several businesses, says which (the caller asks
   *  again with the chosen workspace code). */
  signIn: (login: string, password: string, workspace?: string) => Promise<SignInResult>;
  signOut: () => Promise<void>;
}

export interface Business {
  workspace: string;
  name: string;
}

export interface SignInResult {
  error: string | null;
  businesses?: Business[];
}

const SessionContext = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Session["status"]>("loading");
  const [me, setMe] = useState<Me | null>(null);
  const [units, setUnits] = useState<ReadonlySet<string>>(new Set());

  const load = useCallback(async () => {
    const [meResult, unitsResult] = await Promise.all([api.GET("/api/v1/auth/me"), api.GET("/api/v1/units")]);
    if (!meResult.data || !unitsResult.data) {
      setStatus("signed-out");
      return;
    }
    setMe(meResult.data);
    setUnits(new Set(unitsResult.data.filter((u) => u.enabled).map((u) => String(u.name))));
    setStatus("signed-in");
  }, []);

  useEffect(() => {
    whenSignedOut(() => setStatus("signed-out"));
    if (hasRefreshToken()) {
      void refreshTokens().then((ok) => (ok ? load() : setStatus("signed-out")));
    } else {
      setStatus("signed-out");
    }
  }, [load]);

  const signIn = useCallback(
    async (login: string, password: string, workspace?: string): Promise<SignInResult> => {
      const { data, error } = await api.POST("/api/v1/auth/sign-in", {
        body: { workspace: workspace ?? null, login, password, device_id: deviceId(), device_name: navigator.userAgent.slice(0, 60), channel: "web" },
      });
      if (!data) {
        const choices = (error as { businesses?: Business[] } | undefined)?.businesses;
        return choices?.length ? { error: null, businesses: choices } : { error: errorMessage(error) };
      }
      setTokens(data.access_token, data.refresh_token);
      await load();
      return { error: null };
    },
    [load],
  );

  const signOut = useCallback(async () => {
    await api.POST("/api/v1/auth/sign-out");
    setTokens(null, null);
    setMe(null);
    setStatus("signed-out");
  }, []);

  const value = useMemo<Session>(() => {
    const permissions = new Set(me?.roles.flatMap((r) => r.permissions) ?? []);
    return { status, me, enabledUnits: units, can: (p) => permissions.has(p), signIn, signOut };
  }, [status, me, units, signIn, signOut]);

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
