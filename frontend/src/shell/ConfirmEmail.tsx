import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api, Spinner, useTranslation } from "@/sdk";

import { RegisterLayout } from "./register/RegisterLayout";

/** The page the link in the confirmation email opens. It works signed in or not, and using the link twice is harmless. */
export function ConfirmEmail() {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const token = params.get("token");
  const [phase, setPhase] = useState<"working" | "done" | "failed">(token ? "working" : "failed");
  const started = useRef(false);

  useEffect(() => {
    if (!token || started.current) return;
    started.current = true;
    void api.POST("/api/v1/register/confirm-email", { body: { token } })
      .then(({ response }) => setPhase(response.ok ? "done" : "failed"))
      .catch(() => setPhase("failed"));
  }, [token]);

  return (
    <RegisterLayout step={null} done={new Set()} reachable={new Set()} onGo={() => undefined}>
      <div className="mx-auto max-w-md space-y-4 py-16 text-center">
        {phase === "working" && <p className="flex items-center justify-center gap-2 text-muted"><Spinner /> {t("confirmEmail.working")}</p>}
        {phase === "done" && <>
          <h1 className="text-2xl font-semibold">{t("confirmEmail.doneTitle")}</h1>
          <p className="text-muted">{t("confirmEmail.doneText")}</p>
          <Link to="/" className="inline-block font-medium text-brand-strong underline">{t("confirmEmail.continue")}</Link>
        </>}
        {phase === "failed" && <>
          <h1 className="text-2xl font-semibold">{t("confirmEmail.failedTitle")}</h1>
          <p className="text-muted">{t("confirmEmail.failedText")}</p>
          <Link to="/" className="inline-block font-medium text-brand-strong underline">{t("confirmEmail.continue")}</Link>
        </>}
      </div>
    </RegisterLayout>
  );
}
