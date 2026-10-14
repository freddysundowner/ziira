import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { Alert, Spinner, useSession, useTranslation } from "@/sdk";

import { AuthShell } from "./AuthShell";

/** The page the emailed link opens: it creates the business and signs the owner in. */
export function VerifyRegistration() {
  const { t } = useTranslation();
  const { completeRegistration } = useSession();
  const [params] = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;          // the link works once: do not use it twice (strict mode runs effects twice)
    started.current = true;
    const token = params.get("token");
    if (!token) {
      setError(t("register.badLink"));
      return;
    }
    void completeRegistration(token).then(setError);
  }, [params, completeRegistration, t]);

  return (
    <AuthShell>
      <div className="space-y-4">
        {error ? (
          <>
            <Alert tone="bad">{error}</Alert>
            <Link className="text-sm font-medium text-brand-strong hover:underline" to="/register">{t("register.startAgain")}</Link>
          </>
        ) : (
          <p className="flex items-center gap-2 text-sm text-muted"><Spinner /> {t("register.creating")}</p>
        )}
      </div>
    </AuthShell>
  );
}
