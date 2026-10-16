import { useEffect, useState } from "react";

import { api } from "@/sdk";

import type { ServerCheck } from "./PasswordMeter";

/**
 * Asks the server (the one place that knows the rules) whether the password is acceptable, 400 ms after the last key.
 * When it cannot be reached (offline, too many checks) the answer is "unreachable" and the person may carry on: the
 * sign-up checks again. The password is held in memory only, for as long as it is the one being typed.
 */
export function usePasswordCheck(password: string, email: string): { state: ServerCheck; message: string | null } {
  const key = `${password}\n${email.trim().toLowerCase()}`;
  const [result, setResult] = useState<{ key: string; ok: boolean | null; message: string | null } | null>(null);

  useEffect(() => {
    if (password.length < 8) return;
    let cancelled = false;
    const id = window.setTimeout(() => {
      api.POST("/api/v1/auth/password/check", { body: { password, login: email.trim() || null } })
        .then(({ data }) => { if (!cancelled) setResult({ key, ok: data ? data.ok : null, message: data && !data.ok ? data.message ?? null : null }); })
        .catch(() => { if (!cancelled) setResult({ key, ok: null, message: null }); });
    }, 400);
    return () => { cancelled = true; window.clearTimeout(id); };
  }, [key, password, email]);

  if (password.length < 8) return { state: "idle", message: null };
  if (result?.key !== key) return { state: "checking", message: null };
  return { state: result.ok === true ? "ok" : result.ok === false ? "refused" : "unreachable", message: result.message };
}
