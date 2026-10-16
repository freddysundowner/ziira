import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { useSession, useTranslation } from "@/sdk";
import type { RegistrationCompletion } from "@/sdk/session";

import { Creating, CreatingFailed } from "./register/Creating";
import { RegisterLayout } from "./register/RegisterLayout";

const RETRY_AFTER_MS = 8000;
const SLOW_AFTER_MS = 20000;

/**
 * The page the emailed link opens: it creates the business and signs the owner in. Creating takes a few seconds to a minute,
 * so it shows what is happening; a "try again later" answer (503) is retried once by itself, since nothing is kept on failure.
 */
export function VerifyRegistration() {
  const { t } = useTranslation();
  const { completeRegistration } = useSession();
  const [params] = useSearchParams();
  const [phase, setPhase] = useState<"working" | "retrying" | "failed">("working");
  const [slow, setSlow] = useState(false);
  const [failure, setFailure] = useState<RegistrationCompletion | null>(null);
  const [blockedUntil, setBlockedUntil] = useState<number | null>(null);
  const started = useRef(false);
  const token = params.get("token");

  const attempt = useCallback(async () => {
    if (!token) {
      setFailure({ error: t("register.badLink"), status: 400 });
      setPhase("failed");
      return;
    }
    setPhase("working");
    setFailure(null);
    const run = async (): Promise<RegistrationCompletion> => {
      try { return await completeRegistration(token); } catch { return { error: t("signup.unavailable"), status: 0 }; }
    };
    let result = await run();
    if (result.error && result.status === 503) {          // "try again in a minute": once by itself, then leave it to the person
      setPhase("retrying");
      await new Promise((resolve) => window.setTimeout(resolve, RETRY_AFTER_MS));
      setPhase("working");
      result = await run();
    }
    if (!result.error) return;                             // signed in: the app takes over
    if (result.retryAfter) setBlockedUntil(Date.now() + result.retryAfter * 1000);
    setFailure(result);
    setPhase("failed");
  }, [token, completeRegistration, t]);

  useEffect(() => {
    if (started.current) return;          // the link works once: do not use it twice (strict mode runs effects twice)
    started.current = true;
    void attempt();
  }, [attempt]);

  useEffect(() => {
    if (phase === "failed") return;
    const id = window.setTimeout(() => setSlow(true), SLOW_AFTER_MS);
    return () => window.clearTimeout(id);
  }, [phase]);

  const retryable = !!failure && (failure.status === 503 || failure.status === 0 || failure.status === 429);
  return (
    <RegisterLayout step={null} done={new Set()} reachable={new Set()} onGo={() => undefined} side={null}>
      {phase === "failed" && failure
        ? <CreatingFailed message={failure.error ?? ""} requestId={failure.requestId} canRetry={retryable} blockedUntil={blockedUntil} onRetry={() => { setSlow(false); void attempt(); }} />
        : <Creating slow={slow} retrying={phase === "retrying"} />}
    </RegisterLayout>
  );
}
