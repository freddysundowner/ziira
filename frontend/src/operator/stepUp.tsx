import { useMutation, type UseMutationResult } from "@tanstack/react-query";
import { createContext, type FormEvent, type ReactNode, useCallback, useContext, useRef, useState } from "react";

import { Alert, Button, cleanAuthenticatorCode, Field, Input, isAuthenticatorCode, Modal, toast, useTranslation } from "@/sdk";

import { isStepUp, opApi, opUnwrap } from "./client";
import { useOperatorMe } from "./me";

/** The person closed the confirmation box: the change was not made, and there is nothing to report. */
export class StepUpCancelled extends Error {}

type Runner = <T>(run: () => Promise<T>) => Promise<T>;
const Context = createContext<Runner | null>(null);

interface Waiting {
  resolve: () => void;
  reject: (error: Error) => void;
}

/**
 * Changes need a recent confirmation: the operator's password again (a fresh authenticator code when the platform requires
 * a second factor). A change that the server refuses with "mfa_step_up_required" opens a small box, and when it is
 * confirmed the same change is tried again.
 */
export function StepUpProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation("operator");
  const withCode = useOperatorMe().data?.mfa_mode === "totp";
  const waiting = useRef<Waiting | null>(null);
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("");           // the password, or the authenticator code
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const close = useCallback((reason?: Error) => {
    setOpen(false);
    setCode("");
    setError(null);
    const w = waiting.current;
    waiting.current = null;
    if (reason) w?.reject(reason);
  }, []);

  const ask = useCallback(() => new Promise<void>((resolve, reject) => {
    waiting.current = { resolve, reject };
    setOpen(true);
  }), []);

  const run: Runner = useCallback(async (work) => {
    try {
      return await work();
    } catch (failure) {
      if (!isStepUp(failure)) throw failure;
      await ask();
      return work();
    }
  }, [ask]);

  async function confirm(value: string) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await opUnwrap(opApi.POST("/api/v1/operator/confirm", { body: withCode ? { code: value } : { password: value } }));
      const w = waiting.current;
      close();
      w?.resolve();
    } catch (failure) {
      setError((failure as Error).message);
      setCode("");
    } finally {
      setBusy(false);
    }
  }

  const ready = withCode ? isAuthenticatorCode(code) : code.length > 0;
  const change = (raw: string) => {
    if (!withCode) return setCode(raw);
    const clean = cleanAuthenticatorCode(raw);
    setCode(clean);
    if (clean.length === 6) void confirm(clean);
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (ready) void confirm(code);
  };

  return (
    <Context.Provider value={run}>
      {children}
      <Modal open={open} onClose={() => close(new StepUpCancelled())} title={t("stepUp.title")} size="sm"
        footer={<>
          <Button variant="secondary" onClick={() => close(new StepUpCancelled())}>{t("cancel")}</Button>
          <Button type="submit" form="step-up-form" loading={busy} disabled={!ready}>{t("stepUp.confirm")}</Button>
        </>}>
        <form id="step-up-form" onSubmit={submit} className="space-y-3">
          <p className="text-sm text-muted">{t(withCode ? "stepUp.hint" : "stepUp.passwordHint")}</p>
          {withCode ? (
            <Field label={t("stepUp.codeLabel")}>
              <Input value={code} onChange={(e) => change(e.target.value)} inputMode="numeric" autoComplete="one-time-code" placeholder="123456" autoFocus
                className="text-center font-mono text-lg tracking-[0.4em]" />
            </Field>
          ) : (
            <Field label={t("stepUp.passwordLabel")}>
              <Input type="password" value={code} onChange={(e) => change(e.target.value)} autoComplete="current-password" autoFocus />
            </Field>
          )}
          {error && <Alert tone="bad">{error}</Alert>}
        </form>
      </Modal>
    </Context.Provider>
  );
}

export function useStepUp(): Runner {
  const run = useContext(Context);
  if (!run) throw new Error("useStepUp needs <StepUpProvider>");
  return run;
}

/**
 * A change to the platform: asks for a fresh code when needed, reports a failure in words, and says nothing when the
 * person cancelled the code box.
 */
export function useChange<V, R>(work: (variables: V) => Promise<R>, options: { onSuccess?: (result: R, variables: V) => void; onError?: (error: Error) => void } = {}): UseMutationResult<R, Error, V> {
  const run = useStepUp();
  return useMutation<R, Error, V>({
    mutationFn: (variables) => run(() => work(variables)),
    meta: { silent: true },
    onSuccess: options.onSuccess,
    onError: (error) => {
      if (error instanceof StepUpCancelled) return;
      if (options.onError) options.onError(error);
      else toast(error.message, "bad");
    },
  });
}
