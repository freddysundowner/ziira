import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { ErrorText, useSession, useTranslation } from "@/sdk";

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
    <main className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-sm space-y-3 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        {error ? (
          <>
            <ErrorText>{error}</ErrorText>
            <Link className="text-sm text-brand underline" to="/register">{t("register.startAgain")}</Link>
          </>
        ) : (
          <p className="text-sm text-slate-600">{t("register.creating")}</p>
        )}
      </div>
    </main>
  );
}
