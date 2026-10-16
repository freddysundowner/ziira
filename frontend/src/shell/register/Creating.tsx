import { Link } from "react-router-dom";

import { Alert, Button, formatCountdown, Spinner, useCountdown, useTranslation } from "@/sdk";

const PHASES = ["p1", "p2", "p3", "p4"] as const;

/** While the business is being made: an honest, animated wait (no invented percentage) that says what is happening and, if it drags on, that it is still working. */
export function Creating({ slow, retrying }: { slow: boolean; retrying: boolean }) {
  const { t } = useTranslation();
  return (
    <div className="mx-auto max-w-xl space-y-6 py-8 sm:py-16" aria-busy="true">
      <div className="flex items-center gap-3">
        <Spinner className="h-6 w-6 text-brand" />
        <h1 tabIndex={-1} data-step-heading className="text-3xl font-semibold">{t("signup.creating.title")}</h1>
      </div>
      <p className="text-base text-muted">{t("signup.creating.lead")}</p>
      <div className="h-2 overflow-hidden rounded-full bg-line" role="progressbar" aria-label={t("signup.creating.title")}>
        <div className="h-full w-1/3 animate-pulse rounded-full bg-brand" />
      </div>
      <div className="rounded-xl border border-line bg-surface p-4">
        <p className="mb-2 text-sm font-semibold">{t("signup.creating.what")}</p>
        <ul className="space-y-1.5 text-sm text-muted">{PHASES.map((p) => <li key={p}>{t(`signup.creating.${p}`)}</li>)}</ul>
      </div>
      <div role="status" aria-live="polite">
        {retrying ? <Alert tone="warn">{t("signup.creating.retrying")}</Alert> : slow ? <Alert tone="info">{t("signup.creating.slow")}</Alert> : null}
      </div>
    </div>
  );
}

/** The business could not be made. Nothing was kept and the link still works, so the person can try again. */
export function CreatingFailed({ message, requestId, canRetry, blockedUntil, onRetry }: {
  message: string; requestId?: string; canRetry: boolean; blockedUntil: number | null; onRetry: () => void;
}) {
  const { t } = useTranslation();
  const left = useCountdown(blockedUntil);
  return (
    <div className="mx-auto max-w-xl space-y-5 py-8 sm:py-16">
      <h1 tabIndex={-1} data-step-heading className="text-3xl font-semibold">{t("signup.creating.failedTitle")}</h1>
      <Alert tone="bad">{message}</Alert>
      {canRetry && <p className="text-base text-muted">{t("signup.creating.failedBody")}</p>}
      {left > 0 && <Alert tone="warn">{t("signup.creating.throttled", { time: formatCountdown(left) })}</Alert>}
      {requestId && <p className="text-xs text-muted">{t("signup.creating.reference", { id: requestId })}</p>}
      <div className="flex flex-wrap items-center gap-3">
        {canRetry && <Button size="lg" onClick={onRetry} disabled={left > 0}>{t("signup.creating.tryAgain")}</Button>}
        <Link className="text-sm font-medium text-brand-strong hover:underline" to="/register">{t("register.startAgain")}</Link>
      </div>
    </div>
  );
}
