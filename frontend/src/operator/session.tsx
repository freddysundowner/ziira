import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { hasOperatorToken, opApi, OperatorApiError, opUnwrap, setOperatorToken, whenOperatorSessionEnds } from "./client";

export type SignInResult = { challenge: string } | { signedIn: true } | { error: string; retryAfter?: number };
export type MfaResult = { ok: true } | { ok: false; failure: "wrong" | "expired" | "throttled" | "other"; error: string; retryAfter?: number };

interface OperatorSession {
  signedIn: boolean;
  signIn: (email: string, password: string) => Promise<SignInResult>;
  completeMfa: (challenge: string, code: string) => Promise<MfaResult>;
  signOut: () => Promise<void>;
}

const Context = createContext<OperatorSession | null>(null);

/** The operator's own sign-in state. It knows nothing about business sessions, and they know nothing about it. */
export function OperatorSessionProvider({ children }: { children: ReactNode }) {
  const [signedIn, setSignedIn] = useState(hasOperatorToken());

  useEffect(() => whenOperatorSessionEnds(() => setSignedIn(false)), []);

  const signIn = useCallback(async (email: string, password: string): Promise<SignInResult> => {
    try {
      const answer = await opUnwrap(opApi.POST("/api/v1/operator/sign-in", { body: { email, password } }));
      // With a password alone the answer is the session itself; with a second factor it is a challenge for the code.
      if (answer.access_token) {
        setOperatorToken(answer.access_token);
        setSignedIn(true);
        return { signedIn: true };
      }
      return { challenge: answer.challenge ?? "" };
    } catch (error) {
      return { error: (error as Error).message, retryAfter: error instanceof OperatorApiError && error.status === 429 ? retryAfter(error) : undefined };
    }
  }, []);

  const completeMfa = useCallback(async (challenge: string, code: string): Promise<MfaResult> => {
    try {
      const { access_token } = await opUnwrap(opApi.POST("/api/v1/operator/mfa/verify", { body: { challenge, code } }));
      setOperatorToken(access_token);
      setSignedIn(true);
      return { ok: true };
    } catch (error) {
      const e = error as OperatorApiError;
      const failure = e.code === "challenge_expired" ? "expired" : e.status === 429 ? "throttled" : e.status === 401 ? "wrong" : "other";
      return { ok: false, failure, error: e.message, retryAfter: failure === "throttled" ? retryAfter(e) : undefined };
    }
  }, []);

  const signOut = useCallback(async () => {
    try {
      await opApi.POST("/api/v1/operator/sign-out");
    } finally {
      setOperatorToken(null);
      setSignedIn(false);
    }
  }, []);

  const value = useMemo(() => ({ signedIn, signIn, completeMfa, signOut }), [signedIn, signIn, completeMfa, signOut]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

function retryAfter(error: OperatorApiError): number {
  const seconds = Number(error.body.retry_after);
  return Number.isFinite(seconds) && seconds > 0 ? seconds : 60;
}

export function useOperator(): OperatorSession {
  const value = useContext(Context);
  if (!value) throw new Error("useOperator needs <OperatorSessionProvider>");
  return value;
}
